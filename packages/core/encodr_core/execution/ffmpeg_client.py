from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from encodr_core.execution.errors import FFmpegBinaryNotFoundError, FFmpegProcessError
from encodr_core.execution.models import ExecutionCommandPlan, ExecutionResult


class FFmpegClient:
    def run(self, command_plan: ExecutionCommandPlan) -> ExecutionResult:
        started_at = datetime.now(timezone.utc)
        try:
            result = subprocess.run(
                command_plan.command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise FFmpegBinaryNotFoundError(
                "ffmpeg binary could not be found.",
                file_path=command_plan.input_path,
                command=command_plan.command,
            ) from error

        completed_at = datetime.now(timezone.utc)
        if result.returncode != 0:
            raise FFmpegProcessError(
                "ffmpeg returned a non-zero exit status.",
                file_path=command_plan.input_path,
                command=command_plan.command,
                details={
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        return ExecutionResult(
            mode=command_plan.mode,
            status="completed",
            command=command_plan.command,
            output_path=command_plan.output_path,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            started_at=started_at,
            completed_at=completed_at,
        )
