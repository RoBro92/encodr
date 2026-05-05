from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from pathlib import Path

from app.config import WorkerAgentSettings
from encodr_core.config import deserialise_config_bundle
from encodr_core.execution import (
    BackendSelectionError,
    ExecutionCancelledError,
    ExecutionProgressUpdate,
    ExecutionResult,
    ExecutionRunner,
    FFmpegBinaryNotFoundError,
    FFmpegProcessError,
    build_execution_command_plan,
    calculate_media_savings,
)
from encodr_core.execution.safety import evaluate_execution_safety
from encodr_core.media import encodr_exclusion_reason
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan, build_dry_run_analysis_payload, build_processing_plan
from encodr_core.probe import FFprobeClient, ProbeBinaryNotFoundError, ProbeError
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus

logger = logging.getLogger("encodr.worker_agent.execution")


def _worker_log_extra(event: str, **fields: object) -> dict[str, object]:
    return {
        "event": event,
        "diagnostic_type": "worker_runtime",
        **{key: value for key, value in fields.items() if value is not None},
    }


class RemoteExecutionService:
    def __init__(
        self,
        *,
        settings: WorkerAgentSettings,
        runner: ExecutionRunner | None = None,
        replacement_service: ReplacementService | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or ExecutionRunner()
        self.replacement_service = replacement_service or ReplacementService()

    def execute(
        self,
        *,
        job_id: str,
        plan_payload: dict,
        media_payload: dict,
        job_kind: str = "execution",
        analysis_request_payload: dict | None = None,
        scratch_dir_override: str | None = None,
        preferred_backend: str | None = None,
        allow_cpu_fallback: bool | None = None,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        plan = ProcessingPlan.model_validate(plan_payload)
        media_file, source_path = self._media_file_from_payload(media_payload)
        verifier = OutputVerifier(probe_client=FFprobeClient(binary_path=self.settings.ffprobe_path))

        if self._cancel_requested(cancel_requested):
            return self._cancelled_result(
                mode="cancelled",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                exit_code=None,
                failure_message="Cancellation was requested before remote execution started.",
                started_at=datetime.now(timezone.utc),
            )

        if job_kind == "dry_run":
            return self._execute_analysis(
                media_payload=media_payload,
                analysis_request_payload=analysis_request_payload,
                progress_callback=progress_callback,
            )

        requested_backend = preferred_backend or self.settings.preferred_backend
        allow_fallback = self.settings.allow_cpu_fallback if allow_cpu_fallback is None else allow_cpu_fallback
        scratch_dir = scratch_dir_override or self.settings.scratch_dir or "."
        blocked_result = _blocked_artifact_result(
            source_path=source_path,
            scratch_dir=scratch_dir,
            started_at=datetime.now(timezone.utc),
        )
        if blocked_result is not None:
            logger.warning(
                "remote job skipped because target is an encodr artifact",
                extra=_worker_log_extra(
                    "worker_job_skipped",
                    job_id=job_id,
                    source_path=str(source_path),
                    reason=blocked_result.failure_message,
                    failure_category=blocked_result.failure_category,
                ),
            )
            return blocked_result
        try:
            result = self.runner.execute_plan(
                plan,
                input_path=source_path,
                scratch_dir=scratch_dir,
                ffmpeg_path=self.settings.ffmpeg_path,
                job_id=job_id,
                total_duration_seconds=media_file.container.duration_seconds,
                progress_callback=progress_callback,
                preferred_backend=requested_backend,
                allow_cpu_fallback=allow_fallback,
                cancel_requested=cancel_requested,
            )
        except ExecutionCancelledError as error:
            self._unlink_staged_output(error.details.get("output_path"))
            completed_at = datetime.now(timezone.utc)
            result = self._cancelled_result(
                mode="cancelled",
                command=error.command or [],
                output_path=error.details.get("output_path"),
                stdout=error.details.get("stdout"),
                stderr=error.details.get("stderr"),
                exit_code=error.details.get("exit_code"),
                failure_message=error.message,
                requested_backend=error.details.get("requested_backend"),
                actual_backend=error.details.get("actual_backend"),
                actual_accelerator=error.details.get("actual_accelerator"),
                backend_fallback_used=bool(error.details.get("backend_fallback_used", False)),
                backend_selection_reason=error.details.get("backend_selection_reason"),
                started_at=completed_at,
            )
        except (FFmpegBinaryNotFoundError, FFmpegProcessError) as error:
            completed_at = datetime.now(timezone.utc)
            logger.error(
                "ffmpeg execution failed",
                extra=_worker_log_extra(
                    "ffmpeg_failed",
                    job_id=job_id,
                    source_path=str(source_path),
                    exit_code=error.details.get("exit_code"),
                    requested_backend=error.details.get("requested_backend"),
                    attempted_backend=error.details.get("actual_backend") or error.details.get("requested_backend"),
                    actual_backend=error.details.get("actual_backend"),
                    actual_accelerator=error.details.get("actual_accelerator"),
                    backend_fallback_used=bool(error.details.get("backend_fallback_used", False)),
                    reason=error.message,
                ),
            )
            result = ExecutionResult(
                mode="failed",
                status="failed",
                command=error.command or [],
                output_path=None,
                stdout=error.details.get("stdout"),
                stderr=error.details.get("stderr"),
                failure_message=error.message,
                failure_category="execution_failed",
                exit_code=error.details.get("exit_code"),
                requested_backend=error.details.get("requested_backend"),
                actual_backend=error.details.get("actual_backend"),
                actual_accelerator=error.details.get("actual_accelerator"),
                backend_fallback_used=bool(error.details.get("backend_fallback_used", False)),
                backend_selection_reason=error.details.get("backend_selection_reason"),
                started_at=completed_at,
                completed_at=completed_at,
            )
        except Exception as error:
            completed_at = datetime.now(timezone.utc)
            logger.error(
                "remote execution failed unexpectedly",
                extra=_worker_log_extra(
                    "worker_job_failed",
                    job_id=job_id,
                    source_path=str(source_path),
                    failure_category="execution_failed",
                    reason=str(error),
                    exception_type=type(error).__name__,
                ),
            )
            result = ExecutionResult(
                mode="failed",
                status="failed",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                failure_message=str(error),
                failure_category="execution_failed",
                exit_code=None,
                started_at=completed_at,
                completed_at=completed_at,
            )

        if result.status == "staged":
            if self._cancel_requested(cancel_requested):
                return self._cancelled_result_from_staged(
                    staged_result=result,
                    failure_message="Cancellation was requested before output verification or replacement.",
                )
            if progress_callback is not None:
                progress_callback(
                    ExecutionProgressUpdate(
                        stage="verifying",
                        percent=95.0,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            result = self._verify_and_place(
                job_id=job_id,
                plan=plan,
                media_file=media_file,
                staged_result=result,
                verifier=verifier,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
            )
        return result

    def _execute_analysis(
        self,
        *,
        media_payload: dict,
        analysis_request_payload: dict | None,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
    ) -> ExecutionResult:
        started_at = datetime.now(timezone.utc)
        source_path = str(media_payload.get("file_path") or "")
        blocked_result = _blocked_artifact_result(
            source_path=source_path,
            scratch_dir=None,
            started_at=started_at,
        )
        if blocked_result is not None:
            logger.warning(
                "remote dry run skipped because target is an encodr artifact",
                extra=_worker_log_extra(
                    "worker_job_skipped",
                    source_path=str(source_path),
                    reason=blocked_result.failure_message,
                    failure_category=blocked_result.failure_category,
                ),
            )
            return blocked_result
        if progress_callback is not None:
            progress_callback(
                ExecutionProgressUpdate(
                    stage="probing",
                    percent=10.0,
                    updated_at=started_at,
                )
            )
        try:
            probe_client = FFprobeClient(binary_path=self.settings.ffprobe_path)
            media_file = probe_client.probe_file(source_path)
            if progress_callback is not None:
                progress_callback(
                    ExecutionProgressUpdate(
                        stage="planning",
                        percent=55.0,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            config_bundle = deserialise_config_bundle(
                dict((analysis_request_payload or {}).get("config_bundle") or {})
            )
            plan = build_processing_plan(
                media_file,
                config_bundle,
                source_path=media_file.file_path,
            )
            analysis_payload = build_dry_run_analysis_payload(
                media_file,
                plan,
                ffprobe_path=self.settings.ffprobe_path,
            )
            if progress_callback is not None:
                progress_callback(
                    ExecutionProgressUpdate(
                        stage="summarising",
                        percent=90.0,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            return ExecutionResult(
                mode="dry_run",
                status="completed",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                backend_selection_reason="Dry run analysis inspects and plans files without encoding.",
                analysis_payload=analysis_payload,
                verification=VerificationResult.not_required(),
                replacement=ReplacementResult.not_required(),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        except ProbeBinaryNotFoundError as error:
            logger.error(
                "ffprobe dependency failed",
                extra=_worker_log_extra(
                    "ffprobe_failed",
                    source_path=str(source_path),
                    failure_category="analysis_dependency_missing",
                    reason=error.message,
                ),
            )
            return ExecutionResult(
                mode="dry_run",
                status="failed",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                failure_message=error.message,
                failure_category="analysis_dependency_missing",
                verification=VerificationResult.not_required(),
                replacement=ReplacementResult.not_required(),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        except ProbeError as error:
            logger.error(
                "ffprobe analysis failed",
                extra=_worker_log_extra(
                    "ffprobe_failed",
                    source_path=str(source_path),
                    failure_category="analysis_probe_failed",
                    reason=error.message,
                ),
            )
            return ExecutionResult(
                mode="dry_run",
                status="failed",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                failure_message=error.message,
                failure_category="analysis_probe_failed",
                verification=VerificationResult.not_required(),
                replacement=ReplacementResult.not_required(),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            logger.error(
                "analysis job failed unexpectedly",
                extra=_worker_log_extra(
                    "worker_job_failed",
                    source_path=str(source_path),
                    failure_category="analysis_failed",
                    reason=str(error),
                    exception_type=type(error).__name__,
                ),
            )
            return ExecutionResult(
                mode="dry_run",
                status="failed",
                command=[],
                output_path=None,
                stdout=None,
                stderr=None,
                failure_message=str(error),
                failure_category="analysis_failed",
                verification=VerificationResult.not_required(),
                replacement=ReplacementResult.not_required(),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

    def preview_backend(
        self,
        *,
        job_id: str,
        plan_payload: dict,
        media_payload: dict,
        scratch_dir_override: str | None = None,
        preferred_backend: str | None = None,
        allow_cpu_fallback: bool | None = None,
    ) -> dict[str, object]:
        plan = ProcessingPlan.model_validate(plan_payload)
        media_file, source_path = self._media_file_from_payload(media_payload)
        requested_backend = preferred_backend or self.settings.preferred_backend
        allow_fallback = self.settings.allow_cpu_fallback if allow_cpu_fallback is None else allow_cpu_fallback
        try:
            command_plan = build_execution_command_plan(
                plan,
                input_path=source_path,
                scratch_dir=scratch_dir_override or self.settings.scratch_dir or ".",
                ffmpeg_path=self.settings.ffmpeg_path,
                job_id=job_id,
                preferred_backend=requested_backend,
                allow_cpu_fallback=allow_fallback,
            )
        except BackendSelectionError as error:
            return {
                "requested_backend": error.requested_backend,
                "actual_backend": None,
                "actual_accelerator": None,
                "fallback_used": False,
                "selection_reason": str(error),
            }
        return {
            "requested_backend": command_plan.requested_backend,
            "actual_backend": command_plan.actual_backend,
            "actual_accelerator": command_plan.actual_accelerator,
            "fallback_used": command_plan.fallback_used,
            "selection_reason": command_plan.backend_selection_reason,
        }

    @staticmethod
    def _media_file_from_payload(media_payload: dict) -> tuple[MediaFile, Path]:
        payload = dict(media_payload)
        source_path_raw = str(payload.pop("file_path", "") or "")
        container_payload = payload.get("container")
        if isinstance(container_payload, dict):
            payload["container"] = dict(container_payload)
            if source_path_raw:
                payload["container"]["file_path"] = source_path_raw
                payload["container"].setdefault("file_name", Path(source_path_raw).name)
                extension = Path(source_path_raw).suffix.lower().lstrip(".") or None
                if extension and not payload["container"].get("extension"):
                    payload["container"]["extension"] = extension
        media_file = MediaFile.model_validate(payload)
        source_path = Path(source_path_raw or media_file.file_path)
        return media_file, source_path

    def _verify_and_place(
        self,
        *,
        job_id: str,
        plan: ProcessingPlan,
        media_file: MediaFile,
        staged_result: ExecutionResult,
        verifier: OutputVerifier,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        completed_at = datetime.now(timezone.utc)
        if staged_result.output_path is None:
            return ExecutionResult(
                mode=staged_result.mode,
                status="failed",
                command=staged_result.command,
                output_path=None,
                stdout=staged_result.stdout,
                stderr=staged_result.stderr,
                exit_code=staged_result.exit_code,
                failure_message="The execution runner did not produce a staged output path.",
                failure_category="execution_failed",
                requested_backend=staged_result.requested_backend,
                actual_backend=staged_result.actual_backend,
                actual_accelerator=staged_result.actual_accelerator,
                backend_fallback_used=staged_result.backend_fallback_used,
                backend_selection_reason=staged_result.backend_selection_reason,
                verification=VerificationResult(
                    status=VerificationStatus.FAILED,
                    passed=False,
                    failures=[],
                ),
                replacement=ReplacementResult.not_required(),
                started_at=staged_result.started_at,
                completed_at=completed_at,
            )

        if self._cancel_requested(cancel_requested):
            return self._cancelled_result_from_staged(
                staged_result=staged_result,
                failure_message="Cancellation was requested before output verification.",
            )

        verification = verifier.verify_output(
            staged_output_path=staged_result.output_path,
            plan=plan,
            source_media=media_file,
        )
        metrics = self._probe_media_savings(media_file, staged_result.output_path, verifier)
        source_size = metrics.get("input_size_bytes") or file_size_or_none(media_file.file_path)
        staged_metrics = {
            **metrics,
            "input_size_bytes": source_size,
            "output_size_bytes": file_size_or_none(staged_result.output_path),
        }
        if not verification.passed:
            failure_message = verification.failures[0].message if verification.failures else "Output verification failed."
            logger.error(
                "output verification failed",
                extra=_worker_log_extra(
                    "verification_failed",
                    job_id=job_id,
                    staged_output_path=str(staged_result.output_path),
                    requested_backend=staged_result.requested_backend,
                    actual_backend=staged_result.actual_backend,
                    failure_category="verification_failed",
                    reason=failure_message,
                    verification_failures=[
                        failure.model_dump(mode="json") if hasattr(failure, "model_dump") else failure
                        for failure in verification.failures
                    ],
                ),
            )
            return ExecutionResult(
                mode=staged_result.mode,
                status="failed",
                command=staged_result.command,
                output_path=staged_result.output_path,
                stdout=staged_result.stdout,
                stderr=staged_result.stderr,
                exit_code=staged_result.exit_code,
                failure_message=failure_message,
                failure_category="verification_failed",
                requested_backend=staged_result.requested_backend,
                actual_backend=staged_result.actual_backend,
                actual_accelerator=staged_result.actual_accelerator,
                backend_fallback_used=staged_result.backend_fallback_used,
                backend_selection_reason=staged_result.backend_selection_reason,
                **staged_metrics,
                verification=verification,
                replacement=ReplacementResult.not_required(),
                started_at=staged_result.started_at,
                completed_at=datetime.now(timezone.utc),
            )

        safety_metrics = {
            **metrics,
            "input_size_bytes": source_size,
            "output_size_bytes": metrics.get("output_size_bytes") or staged_metrics["output_size_bytes"],
        }
        compression_failure = self._compression_safety_failure(
            job_id=job_id,
            plan=plan,
            metrics=safety_metrics,
            staged_result=staged_result,
            verification=verification,
        )
        if compression_failure is not None:
            return compression_failure

        if self._cancel_requested(cancel_requested):
            return self._cancelled_result_from_staged(
                staged_result=staged_result,
                failure_message="Cancellation was requested before verified output replacement.",
                verification=verification,
                metrics=staged_metrics,
            )

        if progress_callback is not None:
            progress_callback(
                ExecutionProgressUpdate(
                    stage="replacing",
                    percent=98.0,
                    updated_at=datetime.now(timezone.utc),
                )
            )

        logger.info(
            "replacement started",
            extra=_worker_log_extra(
                "replacement_started",
                job_id=job_id,
                source_path=str(media_file.file_path),
                staged_output_path=str(staged_result.output_path),
            ),
        )
        try:
            replacement = self.replacement_service.place_verified_output(
                source_path=media_file.file_path,
                staged_output_path=staged_result.output_path,
                plan=plan,
            )
        except Exception as error:  # noqa: BLE001
            replacement = ReplacementResult(
                status=ReplacementStatus.FAILED,
                failure_message="Verified output placement failed unexpectedly.",
                details={
                    "operation": "place_verified_output",
                    "source_path": str(media_file.file_path),
                    "staged_output_path": str(staged_result.output_path),
                    "exception_type": type(error).__name__,
                    "exception_message": str(error),
                    "source_exists": Path(media_file.file_path).exists(),
                    "staged_output_exists": Path(staged_result.output_path).exists(),
                },
            )
        if replacement.status != ReplacementStatus.SUCCEEDED:
            logger.error(
                "replacement failed",
                extra=_worker_log_extra(
                    "replacement_failed",
                    job_id=job_id,
                    source_path=str(media_file.file_path),
                    staged_output_path=str(staged_result.output_path),
                    final_output_path=str(replacement.final_output_path) if replacement.final_output_path is not None else None,
                    original_backup_path=str(replacement.original_backup_path) if replacement.original_backup_path is not None else None,
                    replacement_operation=replacement.details.get("operation"),
                    replacement_errno=replacement.details.get("errno"),
                    replacement_reason=replacement.details.get("reason") or replacement.details.get("exception_message"),
                    replacement_details=replacement.details,
                    replacement_failure_message=replacement.failure_message,
                ),
            )
            return ExecutionResult(
                mode=staged_result.mode,
                status="failed",
                command=staged_result.command,
                output_path=staged_result.output_path,
                final_output_path=replacement.final_output_path,
                original_backup_path=replacement.original_backup_path,
                stdout=staged_result.stdout,
                stderr=staged_result.stderr,
                exit_code=staged_result.exit_code,
                failure_message=replacement.failure_message or "Verified output placement failed.",
                failure_category="replacement_failed",
                requested_backend=staged_result.requested_backend,
                actual_backend=staged_result.actual_backend,
                actual_accelerator=staged_result.actual_accelerator,
                backend_fallback_used=staged_result.backend_fallback_used,
                backend_selection_reason=staged_result.backend_selection_reason,
                **staged_metrics,
                verification=verification,
                replacement=replacement,
                started_at=staged_result.started_at,
                completed_at=datetime.now(timezone.utc),
            )

        final_metrics = {
            **metrics,
            "input_size_bytes": source_size,
            "output_size_bytes": file_size_or_none(replacement.final_output_path) or staged_metrics["output_size_bytes"],
        }
        replacement_log = logger.warning if replacement.details.get("backup_delete_failed") or replacement.details.get("staged_cleanup_failed") else logger.info
        replacement_log(
            "replacement succeeded",
            extra=_worker_log_extra(
                "replacement_succeeded",
                job_id=job_id,
                source_path=str(media_file.file_path),
                final_output_path=str(replacement.final_output_path) if replacement.final_output_path is not None else None,
                original_backup_path=str(replacement.original_backup_path) if replacement.original_backup_path is not None else None,
                replacement_operation=replacement.details.get("operation"),
                replacement_errno=replacement.details.get("errno"),
                replacement_reason=replacement.details.get("reason") or replacement.details.get("exception_message"),
                replacement_details=replacement.details,
            ),
        )
        return ExecutionResult(
            mode=staged_result.mode,
            status="completed",
            command=staged_result.command,
            output_path=staged_result.output_path,
            final_output_path=replacement.final_output_path,
            original_backup_path=replacement.original_backup_path,
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            requested_backend=staged_result.requested_backend,
            actual_backend=staged_result.actual_backend,
            actual_accelerator=staged_result.actual_accelerator,
            backend_fallback_used=staged_result.backend_fallback_used,
            backend_selection_reason=staged_result.backend_selection_reason,
            **final_metrics,
            verification=verification,
            replacement=replacement,
            started_at=staged_result.started_at,
            completed_at=datetime.now(timezone.utc),
        )

    def _probe_media_savings(
        self,
        source_media: MediaFile,
        output_path: Path | str,
        verifier: OutputVerifier,
    ) -> dict[str, object]:
        probe_client = getattr(verifier, "probe_client", None)
        if probe_client is None:
            return {
                "output_video_bitrate_unavailable_reason": (
                    "output_video_bitrate_bps is unavailable because no ffprobe client was available "
                    "to measure the staged output."
                ),
                "compression_reduction_unavailable_reason": (
                    "compression_reduction_percent is unavailable because no ffprobe client was available "
                    "to measure the staged output."
                ),
            }
        try:
            output_media = probe_client.probe_file(output_path)
        except ProbeError as error:
            return {
                "output_video_bitrate_unavailable_reason": (
                    "output_video_bitrate_bps is unavailable because ffprobe could not probe the staged "
                    f"output ({error.kind})."
                ),
                "compression_reduction_unavailable_reason": (
                    "compression_reduction_percent is unavailable because ffprobe could not probe the staged "
                    f"output ({error.kind})."
                ),
            }
        return calculate_media_savings(
            source_media,
            output_media,
            ffprobe_path=getattr(probe_client, "binary_path", None),
        )

    def _compression_safety_failure(
        self,
        *,
        job_id: str,
        plan: ProcessingPlan,
        metrics: dict[str, float | int | None],
        staged_result: ExecutionResult,
        verification: VerificationResult,
    ) -> ExecutionResult | None:
        _log_bitrate_measurement_diagnostics(
            job_id=job_id,
            plan=plan,
            metrics=metrics,
            staged_output_path=staged_result.output_path,
        )
        failure = evaluate_execution_safety(plan=plan, metrics=metrics)
        if failure is None:
            return None
        if failure.category == "output_larger_than_input":
            logger.warning(
                "output growth guard triggered",
                extra=_worker_log_extra(
                    "output_growth_guard_triggered",
                    job_id=job_id,
                    **_output_growth_details(plan=plan, metrics=metrics),
                ),
            )
        completed_at = datetime.now(timezone.utc)
        return ExecutionResult(
            mode=staged_result.mode,
            status="manual_review",
            command=staged_result.command,
            output_path=staged_result.output_path,
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            failure_message=failure.message,
            failure_category=failure.category,
            requested_backend=staged_result.requested_backend,
            actual_backend=staged_result.actual_backend,
            actual_accelerator=staged_result.actual_accelerator,
            backend_fallback_used=staged_result.backend_fallback_used,
            backend_selection_reason=staged_result.backend_selection_reason,
            verification=verification,
            replacement=ReplacementResult.not_required(),
            started_at=staged_result.started_at,
            completed_at=completed_at,
            **metrics,
        )

    def _cancelled_result_from_staged(
        self,
        *,
        staged_result: ExecutionResult,
        failure_message: str,
        verification: VerificationResult | None = None,
        metrics: dict[str, float | int | None] | None = None,
    ) -> ExecutionResult:
        self._unlink_staged_output(staged_result.output_path)
        return self._cancelled_result(
            mode="cancelled",
            command=staged_result.command,
            output_path=staged_result.output_path,
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            failure_message=failure_message,
            requested_backend=staged_result.requested_backend,
            actual_backend=staged_result.actual_backend,
            actual_accelerator=staged_result.actual_accelerator,
            backend_fallback_used=staged_result.backend_fallback_used,
            backend_selection_reason=staged_result.backend_selection_reason,
            started_at=staged_result.started_at,
            verification=verification,
            metrics=metrics,
        )

    @staticmethod
    def _cancelled_result(
        *,
        mode: str,
        command: list[str],
        output_path: Path | str | None,
        stdout: str | None,
        stderr: str | None,
        exit_code: int | None,
        failure_message: str,
        requested_backend: str | None = None,
        actual_backend: str | None = None,
        actual_accelerator: str | None = None,
        backend_fallback_used: bool = False,
        backend_selection_reason: str | None = None,
        started_at: datetime,
        verification: VerificationResult | None = None,
        metrics: dict[str, float | int | None] | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            mode=mode,
            status="cancelled",
            command=command,
            output_path=Path(output_path) if output_path is not None else None,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            failure_message=failure_message,
            failure_category="cancelled_by_operator",
            requested_backend=requested_backend,
            actual_backend=actual_backend,
            actual_accelerator=actual_accelerator,
            backend_fallback_used=backend_fallback_used,
            backend_selection_reason=backend_selection_reason,
            verification=verification or VerificationResult.not_required(),
            replacement=ReplacementResult.not_required(),
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            **(metrics or {}),
        )

    @staticmethod
    def _cancel_requested(callback: Callable[[], bool] | None) -> bool:
        if callback is None:
            return False
        try:
            return bool(callback())
        except Exception:
            return False

    @staticmethod
    def _unlink_staged_output(path: Path | str | None) -> None:
        if path is None:
            return
        try:
            Path(path).unlink()
        except FileNotFoundError:
            return
        except OSError:
            return


def file_size_or_none(path: Path | str | None) -> int | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved.stat().st_size


def _output_growth_details(
    *,
    plan: ProcessingPlan,
    metrics: dict[str, float | int | None],
) -> dict[str, float | int | None]:
    input_size = metrics.get("input_size_bytes")
    output_size = metrics.get("output_size_bytes")
    growth_percent = None
    if input_size is not None and output_size is not None and float(input_size) > 0:
        growth_percent = ((float(output_size) - float(input_size)) / float(input_size)) * 100.0
    return {
        "input_size_bytes": input_size,
        "output_size_bytes": output_size,
        "output_growth_percent": growth_percent,
        "output_growth_guard_percent": plan.video.output_larger_than_input_review_percent,
    }


def _log_bitrate_measurement_diagnostics(
    *,
    job_id: str,
    plan: ProcessingPlan,
    metrics: dict[str, object],
    staged_output_path: Path | str | None,
) -> None:
    if not plan.video.transcode_required or plan.video.minimum_output_bitrate_bps is None:
        return
    output_bitrate = metrics.get("output_video_bitrate_bps")
    if metrics.get("output_video_bitrate_source") == "derived_video_size_duration":
        logger.warning(
            "bitrate fallback used",
            extra=_worker_log_extra(
                "bitrate_fallback_used",
                job_id=job_id,
                staged_output_path=str(staged_output_path) if staged_output_path is not None else None,
                output_video_bitrate_bps=output_bitrate,
                output_video_bitrate_source=metrics.get("output_video_bitrate_source"),
                video_output_size_bytes=metrics.get("video_output_size_bytes"),
                output_size_bytes=metrics.get("output_size_bytes"),
                output_duration_seconds=metrics.get("output_duration_seconds"),
                minimum_output_bitrate_bps=plan.video.minimum_output_bitrate_bps,
            ),
        )
    elif output_bitrate is None:
        logger.warning(
            "bitrate measurement unavailable",
            extra=_worker_log_extra(
                "bitrate_measurement_unavailable",
                job_id=job_id,
                staged_output_path=str(staged_output_path) if staged_output_path is not None else None,
                reason=metrics.get("output_video_bitrate_unavailable_reason")
                or "output_video_bitrate_bps is unavailable.",
                video_output_size_bytes=metrics.get("video_output_size_bytes"),
                output_size_bytes=metrics.get("output_size_bytes"),
                output_duration_seconds=metrics.get("output_duration_seconds"),
                minimum_output_bitrate_bps=plan.video.minimum_output_bitrate_bps,
            ),
        )


def _blocked_artifact_result(
    *,
    source_path: Path | str,
    scratch_dir: Path | str | None,
    started_at: datetime,
) -> ExecutionResult | None:
    reason = encodr_exclusion_reason(source_path, scratch_dir=scratch_dir)
    if reason is None:
        return None
    return ExecutionResult(
        mode="blocked",
        status="skipped",
        command=[],
        output_path=None,
        failure_message=reason,
        failure_category="excluded_encodr_artifact",
        verification=VerificationResult.not_required(),
        replacement=ReplacementResult.not_required(),
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
