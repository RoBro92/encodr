from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from encodr_core.execution import ExecutionResult, ExecutionRunner, FFmpegProcessError, FFmpegBinaryNotFoundError
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.replacement import ReplacementResult, ReplacementService, ReplacementStatus
from encodr_core.verification import OutputVerifier, VerificationResult, VerificationStatus
from encodr_db.models import Job
from encodr_db.repositories import JobRepository, TrackedFileRepository


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
            stdout=staged_result.stdout,
            stderr=staged_result.stderr,
            exit_code=staged_result.exit_code,
            verification=verification,
            replacement=replacement,
            started_at=staged_result.started_at,
            completed_at=datetime.now(timezone.utc),
        )
