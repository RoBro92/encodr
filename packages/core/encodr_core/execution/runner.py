from __future__ import annotations

import inspect
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from encodr_core.execution.backend_selection import BackendSelectionError
from encodr_core.execution.ffmpeg_builder import build_execution_command_plan
from encodr_core.execution.ffmpeg_client import FFmpegClient
from encodr_core.execution.models import ExecutionProgressUpdate, ExecutionResult
from encodr_core.planning import ProcessingPlan
from encodr_core.planning.enums import PlanAction


class ExecutionRunner:
    def __init__(self, ffmpeg_client: FFmpegClient | None = None) -> None:
        self.ffmpeg_client = ffmpeg_client or FFmpegClient()

    def execute_plan(
        self,
        plan: ProcessingPlan,
        *,
        input_path: Path | str,
        scratch_dir: Path | str,
        ffmpeg_path: Path | str = "/usr/bin/ffmpeg",
        job_id: str | None = None,
        total_duration_seconds: float | None = None,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
        preferred_backend: str = "cpu_only",
        allow_cpu_fallback: bool = True,
        process_started_callback: Callable[[subprocess.Popen[str]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        started_at = datetime.now(timezone.utc)
        try:
            command_plan = build_execution_command_plan(
                plan,
                input_path=input_path,
                scratch_dir=scratch_dir,
                ffmpeg_path=ffmpeg_path,
                job_id=job_id,
                preferred_backend=preferred_backend,
                allow_cpu_fallback=allow_cpu_fallback,
            )
        except BackendSelectionError as error:
            completed_at = datetime.now(timezone.utc)
            return ExecutionResult(
                mode="failed",
                status="failed",
                command=[],
                output_path=None,
                failure_message=str(error),
                failure_category="backend_unavailable",
                requested_backend=error.requested_backend,
                actual_backend=None,
                actual_accelerator=None,
                backend_fallback_used=False,
                backend_selection_reason=str(error),
                started_at=started_at,
                completed_at=completed_at,
            )

        if plan.action == PlanAction.SKIP:
            skipped_reason = skipped_reason_for_plan(plan)
            return ExecutionResult(
                mode="skip",
                status="skipped",
                command=[],
                output_path=None,
                failure_message=skipped_reason,
                failure_category="skipped_by_policy",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        if plan.action == PlanAction.MANUAL_REVIEW:
            return ExecutionResult(
                mode="manual_review",
                status="manual_review",
                command=[],
                output_path=None,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        if command_plan.output_path is not None:
            command_plan.output_path.parent.mkdir(parents=True, exist_ok=True)

        run_signature = inspect.signature(self.ffmpeg_client.run)
        if "total_duration_seconds" in run_signature.parameters or "progress_callback" in run_signature.parameters:
            execution_result = self.ffmpeg_client.run(
                command_plan,
                total_duration_seconds=total_duration_seconds,
                progress_callback=progress_callback,
                process_started_callback=process_started_callback,
                cancel_requested=cancel_requested,
            )
        else:
            execution_result = self.ffmpeg_client.run(command_plan)
        execution_result.status = "staged"
        return execution_result


def skipped_reason_for_plan(plan: ProcessingPlan) -> str:
    for reason in plan.reasons:
        if reason.message:
            return reason.message
        if reason.code:
            return reason.code.replace("_", " ")
    if plan.is_already_compliant:
        return "Already efficient under the active processing policy."
    return "Skipped because no replacement work was required."
