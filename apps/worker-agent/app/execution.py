from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import WorkerAgentSettings
from encodr_core.execution import ExecutionResult, ExecutionRunner, FFmpegBinaryNotFoundError, FFmpegProcessError
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.probe import FFprobeClient
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

    def execute(self, *, job_id: str, plan_payload: dict, media_payload: dict) -> ExecutionResult:
        plan = ProcessingPlan.model_validate(plan_payload)
        media_file = MediaFile.model_validate(media_payload)
        verifier = OutputVerifier(probe_client=FFprobeClient(binary_path=self.settings.ffprobe_path))

        try:
            result = self.runner.execute_plan(
                plan,
                input_path=media_file.file_path,
                scratch_dir=self.settings.scratch_dir or ".",
                ffmpeg_path=self.settings.ffmpeg_path,
                job_id=job_id,
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
            result = self._verify_and_place(
                plan=plan,
                media_file=media_file,
                staged_result=result,
                verifier=verifier,
            )
        return result

    def _verify_and_place(
        self,
        *,
        plan: ProcessingPlan,
        media_file: MediaFile,
        staged_result: ExecutionResult,
        verifier: OutputVerifier,
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

        verification = verifier.verify_output(
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


def file_size_or_none(path: Path | str | None) -> int | None:
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved.stat().st_size
