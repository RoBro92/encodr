from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from pathlib import Path
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config import ConfigBundle
from encodr_core.execution import (
    BackendSelectionError,
    ExecutionProgressUpdate,
    ExecutionResult,
    ExecutionRunner,
    FFmpegBinaryNotFoundError,
    FFmpegProcessError,
    build_execution_command_plan,
    calculate_media_savings,
    normalise_backend_preference,
)
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.probe import ProbeError
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db.models import Job
from encodr_db.repositories import JobRepository, TrackedFileRepository
from encodr_shared import collect_runtime_telemetry, load_execution_preferences

logger = logging.getLogger("encodr.worker.loop")


@dataclass(slots=True)
class WorkerRunSummary:
    processed_job: bool
    job_id: str | None = None
    final_status: str | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(slots=True)
class WorkerStatusSnapshot:
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_processed_job_id: str | None = None
    last_result_status: str | None = None
    last_failure_message: str | None = None
    processed_jobs: int = 0
    current_job_id: str | None = None
    current_backend: str | None = None
    current_stage: str | None = None
    current_progress_percent: int | None = None
    current_progress_updated_at: datetime | None = None
    telemetry: dict[str, object] | None = None


class WorkerStatusTracker:
    def __init__(self) -> None:
        self._snapshot = WorkerStatusSnapshot()

    def snapshot(self) -> WorkerStatusSnapshot:
        return WorkerStatusSnapshot(
            last_run_started_at=self._snapshot.last_run_started_at,
            last_run_completed_at=self._snapshot.last_run_completed_at,
            last_processed_job_id=self._snapshot.last_processed_job_id,
            last_result_status=self._snapshot.last_result_status,
            last_failure_message=self._snapshot.last_failure_message,
            processed_jobs=self._snapshot.processed_jobs,
            current_job_id=self._snapshot.current_job_id,
            current_backend=self._snapshot.current_backend,
            current_stage=self._snapshot.current_stage,
            current_progress_percent=self._snapshot.current_progress_percent,
            current_progress_updated_at=self._snapshot.current_progress_updated_at,
            telemetry=dict(self._snapshot.telemetry or {}) or None,
        )

    def record_idle_run(self, *, started_at: datetime, completed_at: datetime) -> None:
        self._snapshot.last_run_started_at = started_at
        self._snapshot.last_run_completed_at = completed_at
        self._snapshot.last_processed_job_id = None
        self._snapshot.last_result_status = "idle"
        self._snapshot.last_failure_message = None
        self._snapshot.current_job_id = None
        self._snapshot.current_backend = None
        self._snapshot.current_stage = None
        self._snapshot.current_progress_percent = None
        self._snapshot.current_progress_updated_at = completed_at
        self._snapshot.telemetry = collect_runtime_telemetry()

    def record_processed_run(
        self,
        *,
        job_id: str,
        final_status: str,
        started_at: datetime,
        completed_at: datetime,
        failure_message: str | None,
    ) -> None:
        self._snapshot.last_run_started_at = started_at
        self._snapshot.last_run_completed_at = completed_at
        self._snapshot.last_processed_job_id = job_id
        self._snapshot.last_result_status = final_status
        self._snapshot.last_failure_message = failure_message
        self._snapshot.processed_jobs += 1
        self._snapshot.current_job_id = None
        self._snapshot.current_backend = None
        self._snapshot.current_stage = None
        self._snapshot.current_progress_percent = None
        self._snapshot.current_progress_updated_at = completed_at
        self._snapshot.telemetry = collect_runtime_telemetry()

    def record_job_started(
        self,
        *,
        job_id: str,
        backend: str | None,
        started_at: datetime,
    ) -> None:
        self._snapshot.current_job_id = job_id
        self._snapshot.current_backend = backend
        self._snapshot.current_stage = "starting"
        self._snapshot.current_progress_percent = 0
        self._snapshot.current_progress_updated_at = started_at
        self._snapshot.telemetry = collect_runtime_telemetry(current_backend=backend)

    def record_progress(
        self,
        *,
        stage: str,
        percent: float | None,
        updated_at: datetime,
    ) -> None:
        self._snapshot.current_stage = stage
        self._snapshot.current_progress_percent = int(percent) if percent is not None else None
        self._snapshot.current_progress_updated_at = updated_at
        self._snapshot.telemetry = collect_runtime_telemetry(current_backend=self._snapshot.current_backend)


class WorkerExecutionService:
    def __init__(
        self,
        runner: ExecutionRunner | None = None,
        verifier: OutputVerifier | None = None,
        replacement_service: ReplacementService | None = None,
    ) -> None:
        self.runner = runner or ExecutionRunner()
        self.verifier = verifier or OutputVerifier()
        self.replacement_service = replacement_service or ReplacementService()

    def execute_job(
        self,
        session: Session,
        *,
        job_id: str,
        plan: ProcessingPlan,
        media_file: MediaFile,
        ffmpeg_path: Path | str,
        scratch_dir: Path | str,
        preferred_backend: str = "cpu_only",
        allow_cpu_fallback: bool = True,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
    ) -> ExecutionResult:
        job_repository = JobRepository(session)
        tracked_file_repository = TrackedFileRepository(session)

        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' could not be found.")

        try:
            result = self.runner.execute_plan(
                plan,
                input_path=media_file.file_path,
                scratch_dir=scratch_dir,
                ffmpeg_path=ffmpeg_path,
                job_id=job.id,
                total_duration_seconds=media_file.container.duration_seconds,
                progress_callback=progress_callback,
                preferred_backend=preferred_backend,
                allow_cpu_fallback=allow_cpu_fallback,
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
                started_at=job.started_at or completed_at,
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
                started_at=job.started_at or completed_at,
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
                progress_callback=progress_callback,
            )

        job_repository.mark_result(job, result)
        tracked_file_repository.update_file_state_from_execution_result(job.tracked_file, plan, result)
        session.flush()
        return result

    def _verify_and_place(
        self,
        *,
        plan: ProcessingPlan,
        media_file: MediaFile,
        staged_result: ExecutionResult,
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

        verification = self.verifier.verify_output(
            staged_output_path=staged_result.output_path,
            plan=plan,
            source_media=media_file,
        )
        metrics = self._probe_media_savings(media_file, staged_result.output_path)
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

    def _probe_media_savings(self, source_media: MediaFile, output_path: Path | str) -> dict[str, float | int | None]:
        probe_client = getattr(self.verifier, "probe_client", None)
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


class LocalWorkerLoop:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config_bundle: ConfigBundle,
        *,
        worker_name: str = "worker-local",
        poll_interval_seconds: float = 2.0,
        execution_service: WorkerExecutionService | None = None,
        status_tracker: WorkerStatusTracker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config_bundle = config_bundle
        self.worker_name = worker_name
        self.poll_interval_seconds = poll_interval_seconds
        self.execution_service = execution_service or WorkerExecutionService()
        self.status_tracker = status_tracker or WorkerStatusTracker()

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def run_once(self) -> bool:
        return self.run_once_with_summary().processed_job

    def run_once_with_summary(self) -> WorkerRunSummary:
        run_started_at = datetime.now(timezone.utc)
        with self.session_factory() as session:
            jobs = JobRepository(session)
            execution_preferences = load_execution_preferences(self.config_bundle.app.data_dir)
            job = next(
                (
                    candidate
                    for candidate in jobs.fetch_next_pending_local_jobs()
                    if _job_is_locally_compatible(
                        plan=ProcessingPlan.model_validate(candidate.plan_snapshot.payload),
                        ffmpeg_path=self.config_bundle.app.media.ffmpeg_path,
                        preferred_backend=str(execution_preferences["preferred_backend"]),
                        allow_cpu_fallback=bool(execution_preferences["allow_cpu_fallback"]),
                    )
                ),
                None,
            )
            if job is None:
                completed_at = datetime.now(timezone.utc)
                self.status_tracker.record_idle_run(
                    started_at=run_started_at,
                    completed_at=completed_at,
                )
                return WorkerRunSummary(
                    processed_job=False,
                    started_at=run_started_at,
                    completed_at=completed_at,
                )

            plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
            media_file = MediaFile.model_validate(job.plan_snapshot.probe_snapshot.payload)
            backend_preview = _preview_local_backend(
                plan=plan,
                media_file=media_file,
                ffmpeg_path=self.config_bundle.app.media.ffmpeg_path,
                scratch_dir=self.config_bundle.app.scratch_dir,
                preferred_backend=str(execution_preferences["preferred_backend"]),
                allow_cpu_fallback=bool(execution_preferences["allow_cpu_fallback"]),
                job_id=job.id,
            )
            jobs.mark_running(
                job,
                worker_name=self.worker_name,
                requested_backend=str(execution_preferences["preferred_backend"]),
            )
            self.status_tracker.record_job_started(
                job_id=job.id,
                backend=str(backend_preview["actual_backend"] or backend_preview["requested_backend"] or normalise_backend_preference(str(execution_preferences["preferred_backend"]))),
                started_at=job.started_at or run_started_at,
            )
            # Commit the running transition before execution starts so Postgres-backed
            # progress updates can use separate sessions without blocking on this row.
            session.commit()

            logger.info("processing job %s for %s", job.id, media_file.file_name)
            progress_reporter = self._build_progress_reporter(job_id=job.id, session=session)
            result = self.execution_service.execute_job(
                session,
                job_id=job.id,
                plan=plan,
                media_file=media_file,
                ffmpeg_path=self.config_bundle.app.media.ffmpeg_path,
                scratch_dir=self.config_bundle.app.scratch_dir,
                preferred_backend=str(execution_preferences["preferred_backend"]),
                allow_cpu_fallback=bool(execution_preferences["allow_cpu_fallback"]),
                progress_callback=progress_reporter,
            )
            session.commit()
            self.status_tracker.record_processed_run(
                job_id=job.id,
                final_status=result.status,
                started_at=run_started_at,
                completed_at=result.completed_at,
                failure_message=result.failure_message,
            )
            return WorkerRunSummary(
                processed_job=True,
                job_id=job.id,
                final_status=result.status,
                failure_message=result.failure_message,
                started_at=run_started_at,
                completed_at=result.completed_at,
            )

    def _build_progress_reporter(
        self,
        *,
        job_id: str,
        session: Session,
    ) -> Callable[[ExecutionProgressUpdate], None]:
        dialect_name = session.bind.dialect.name if session.bind is not None else None

        def report(update: ExecutionProgressUpdate) -> None:
            self.status_tracker.record_progress(
                stage=update.stage,
                percent=update.percent,
                updated_at=update.updated_at,
            )
            if dialect_name == "sqlite":
                progress_job = session.get(Job, job_id)
                if progress_job is None:
                    return
                JobRepository(session).record_progress(progress_job, update=update)
                return
            with self.session_factory() as progress_session:
                progress_job = progress_session.get(Job, job_id)
                if progress_job is None:
                    return
                JobRepository(progress_session).record_progress(progress_job, update=update)
                progress_session.commit()

        return report


def file_size_or_none(path: Path | str | None) -> int | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved.stat().st_size


def _job_is_locally_compatible(
    *,
    plan: ProcessingPlan,
    ffmpeg_path: Path | str,
    preferred_backend: str,
    allow_cpu_fallback: bool,
) -> bool:
    if not plan.video.transcode_required:
        return True
    try:
        from encodr_core.execution import select_execution_backend

        select_execution_backend(
            ffmpeg_path=ffmpeg_path,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            target_codec=plan.video.target_codec,
        )
    except BackendSelectionError:
        return False
    return True


def _preview_local_backend(
    *,
    plan: ProcessingPlan,
    media_file: MediaFile,
    ffmpeg_path: Path | str,
    scratch_dir: Path | str,
    preferred_backend: str,
    allow_cpu_fallback: bool,
    job_id: str,
) -> dict[str, object]:
    try:
        command_plan = build_execution_command_plan(
            plan,
            input_path=media_file.file_path,
            scratch_dir=scratch_dir,
            ffmpeg_path=ffmpeg_path,
            job_id=job_id,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
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
