from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.config import WorkerAgentSettings
from encodr_core.config import deserialise_config_bundle
from encodr_core.execution import (
    BackendSelectionError,
    ExecutionProgressUpdate,
    ExecutionResult,
    ExecutionRunner,
    FFmpegBinaryNotFoundError,
    FFmpegProcessError,
    build_execution_command_plan,
    calculate_media_savings,
)
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan, build_dry_run_analysis_payload, build_processing_plan
from encodr_core.probe import FFprobeClient, ProbeBinaryNotFoundError, ProbeError
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus


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
    ) -> ExecutionResult:
        plan = ProcessingPlan.model_validate(plan_payload)
        media_file, source_path = self._media_file_from_payload(media_payload)
        verifier = OutputVerifier(probe_client=FFprobeClient(binary_path=self.settings.ffprobe_path))

        if job_kind == "dry_run":
            return self._execute_analysis(
                media_payload=media_payload,
                analysis_request_payload=analysis_request_payload,
                progress_callback=progress_callback,
            )

        requested_backend = preferred_backend or self.settings.preferred_backend
        allow_fallback = self.settings.allow_cpu_fallback if allow_cpu_fallback is None else allow_cpu_fallback
        scratch_dir = scratch_dir_override or self.settings.scratch_dir or "."
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
            )
        except (FFmpegBinaryNotFoundError, FFmpegProcessError) as error:
            completed_at = datetime.now(timezone.utc)
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
            if progress_callback is not None:
                progress_callback(
                    ExecutionProgressUpdate(
                        stage="verifying",
                        percent=95.0,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            result = self._verify_and_place(
                plan=plan,
                media_file=media_file,
                staged_result=result,
                verifier=verifier,
                progress_callback=progress_callback,
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
        plan: ProcessingPlan,
        media_file: MediaFile,
        staged_result: ExecutionResult,
        verifier: OutputVerifier,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
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

        verification = verifier.verify_output(
            staged_output_path=staged_result.output_path,
            plan=plan,
            source_media=media_file,
        )
        metrics = self._probe_media_savings(media_file, staged_result.output_path, verifier)
        staged_metrics = {**metrics, "output_size_bytes": file_size_or_none(staged_result.output_path)}
        if not verification.passed:
            failure_message = verification.failures[0].message if verification.failures else "Output verification failed."
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

        compression_failure = self._compression_safety_failure(
            plan=plan,
            metrics=metrics,
            staged_result=staged_result,
            verification=verification,
        )
        if compression_failure is not None:
            return compression_failure

        if progress_callback is not None:
            progress_callback(
                ExecutionProgressUpdate(
                    stage="replacing",
                    percent=98.0,
                    updated_at=datetime.now(timezone.utc),
                )
            )

        replacement = self.replacement_service.place_verified_output(
            source_path=media_file.file_path,
            staged_output_path=staged_result.output_path,
            plan=plan,
        )
        if replacement.status != ReplacementStatus.SUCCEEDED:
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
            "output_size_bytes": file_size_or_none(replacement.final_output_path) or staged_metrics["output_size_bytes"],
        }
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
    ) -> dict[str, float | int | None]:
        probe_client = getattr(verifier, "probe_client", None)
        if probe_client is None:
            return {}
        try:
            output_media = probe_client.probe_file(output_path)
        except ProbeError:
            return {}
        return calculate_media_savings(
            source_media,
            output_media,
            ffprobe_path=getattr(probe_client, "binary_path", None),
        )

    def _compression_safety_failure(
        self,
        *,
        plan: ProcessingPlan,
        metrics: dict[str, float | int | None],
        staged_result: ExecutionResult,
        verification: VerificationResult,
    ) -> ExecutionResult | None:
        limit = plan.video.max_allowed_video_reduction_percent
        if not plan.video.transcode_required or limit is None:
            return None
        reduction = metrics.get("compression_reduction_percent")
        completed_at = datetime.now(timezone.utc)
        if reduction is None:
            return ExecutionResult(
                mode=staged_result.mode,
                status="manual_review",
                command=staged_result.command,
                output_path=staged_result.output_path,
                stdout=staged_result.stdout,
                stderr=staged_result.stderr,
                exit_code=staged_result.exit_code,
                failure_message="Video reduction could not be measured safely, so the output requires manual review.",
                failure_category="compression_safety_unmeasurable",
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
        if reduction <= limit:
            return None
        return ExecutionResult(
            mode=staged_result.mode,
            status="manual_review",
            command=staged_result.command,
            output_path=staged_result.output_path,
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            failure_message=(
                f"Video compression reduced the picture by {reduction:.1f}% which exceeds the "
                f"configured safety limit of {limit}%."
            ),
            failure_category="compression_safety_exceeded",
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


def file_size_or_none(path: Path | str | None) -> int | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved.stat().st_size
