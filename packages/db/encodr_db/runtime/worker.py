from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config import ConfigBundle
from encodr_core.execution import ExecutionResult, ExecutionRunner, FFmpegBinaryNotFoundError, FFmpegProcessError
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db.models import Job
from encodr_db.repositories import JobRepository, TrackedFileRepository

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
        )

    def record_idle_run(self, *, started_at: datetime, completed_at: datetime) -> None:
        self._snapshot.last_run_started_at = started_at
        self._snapshot.last_run_completed_at = completed_at
        self._snapshot.last_processed_job_id = None
        self._snapshot.last_result_status = "idle"
        self._snapshot.last_failure_message = None

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
            result = self._verify_and_place(
                plan=plan,
                media_file=media_file,
                staged_result=result,
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
                output_size_bytes=file_size_or_none(staged_result.output_path),
                verification=verification,
                replacement=ReplacementResult.not_required(),
                started_at=staged_result.started_at,
                completed_at=datetime.now(timezone.utc),
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
                output_size_bytes=file_size_or_none(staged_result.output_path),
                verification=verification,
                replacement=replacement,
                started_at=staged_result.started_at,
                completed_at=datetime.now(timezone.utc),
            )

        return ExecutionResult(
            mode=staged_result.mode,
            status="completed",
            command=staged_result.command,
            output_path=staged_result.output_path,
            final_output_path=replacement.final_output_path,
            original_backup_path=replacement.original_backup_path,
            output_size_bytes=file_size_or_none(replacement.final_output_path) or file_size_or_none(staged_result.output_path),
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            verification=verification,
            replacement=replacement,
            started_at=staged_result.started_at,
            completed_at=datetime.now(timezone.utc),
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
            job = jobs.fetch_next_pending_job()
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

            jobs.mark_running(job, worker_name=self.worker_name)
            plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
            media_file = MediaFile.model_validate(job.plan_snapshot.probe_snapshot.payload)

            logger.info("processing job %s for %s", job.id, media_file.file_name)
            result = self.execution_service.execute_job(
                session,
                job_id=job.id,
                plan=plan,
                media_file=media_file,
                ffmpeg_path=self.config_bundle.app.media.ffmpeg_path,
                scratch_dir=self.config_bundle.app.scratch_dir,
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


def file_size_or_none(path: Path | str | None) -> int | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved.stat().st_size
