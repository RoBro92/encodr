from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from encodr_core.execution.errors import ExecutionCancelledError, FFmpegBinaryNotFoundError, FFmpegProcessError
from encodr_core.execution.models import ExecutionCommandPlan, ExecutionProgressUpdate, ExecutionResult


class FFmpegClient:
    def run(
        self,
        command_plan: ExecutionCommandPlan,
        *,
        total_duration_seconds: float | None = None,
        progress_callback: Callable[[ExecutionProgressUpdate], None] | None = None,
        process_started_callback: Callable[[subprocess.Popen[str]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        started_at = datetime.now(timezone.utc)
        try:
            process = subprocess.Popen(
                command_plan.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as error:
            raise FFmpegBinaryNotFoundError(
                "ffmpeg binary could not be found.",
                file_path=command_plan.input_path,
                command=command_plan.command,
                details={
                    "requested_backend": command_plan.requested_backend,
                    "actual_backend": command_plan.actual_backend,
                    "actual_accelerator": command_plan.actual_accelerator,
                    "backend_fallback_used": command_plan.fallback_used,
                    "backend_selection_reason": command_plan.backend_selection_reason,
                },
            ) from error
        if process_started_callback is not None:
            process_started_callback(process)

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=self._drain_pipe,
            args=(process.stderr, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()

        progress_payload: dict[str, str] = {}
        assert process.stdout is not None
        for raw_line in process.stdout:
            stdout_lines.append(raw_line)
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            progress_payload[key] = value
            if key == "progress":
                progress_update = self._parse_progress_payload(
                    progress_payload,
                    total_duration_seconds=total_duration_seconds,
                )
                if progress_update is not None and progress_callback is not None:
                    progress_callback(progress_update)
                progress_payload = {}

        returncode = process.wait()
        stderr_thread.join()
        completed_at = datetime.now(timezone.utc)
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        if cancel_requested is not None and cancel_requested():
            raise ExecutionCancelledError(
                "ffmpeg execution was cancelled by the operator.",
                file_path=command_plan.input_path,
                command=command_plan.command,
                details={
                    "exit_code": returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "output_path": str(command_plan.output_path) if command_plan.output_path is not None else None,
                    "requested_backend": command_plan.requested_backend,
                    "actual_backend": command_plan.actual_backend,
                    "actual_accelerator": command_plan.actual_accelerator,
                    "backend_fallback_used": command_plan.fallback_used,
                    "backend_selection_reason": command_plan.backend_selection_reason,
                },
            )
        if returncode != 0:
            raise FFmpegProcessError(
                "ffmpeg returned a non-zero exit status.",
                file_path=command_plan.input_path,
                command=command_plan.command,
                details={
                    "exit_code": returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "requested_backend": command_plan.requested_backend,
                    "actual_backend": command_plan.actual_backend,
                    "actual_accelerator": command_plan.actual_accelerator,
                    "backend_fallback_used": command_plan.fallback_used,
                    "backend_selection_reason": command_plan.backend_selection_reason,
                },
            )

        return ExecutionResult(
            mode=command_plan.mode,
            status="completed",
            command=command_plan.command,
            output_path=command_plan.output_path,
            requested_backend=command_plan.requested_backend,
            actual_backend=command_plan.actual_backend,
            actual_accelerator=command_plan.actual_accelerator,
            backend_fallback_used=command_plan.fallback_used,
            backend_selection_reason=command_plan.backend_selection_reason,
            exit_code=returncode,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            completed_at=completed_at,
        )

    @staticmethod
    def _drain_pipe(pipe, lines: list[str]) -> None:
        if pipe is None:
            return
        try:
            for line in pipe:
                lines.append(line)
        finally:
            pipe.close()

    @staticmethod
    def _parse_progress_payload(
        payload: dict[str, str],
        *,
        total_duration_seconds: float | None,
    ) -> ExecutionProgressUpdate | None:
        if not payload:
            return None
        out_time_seconds = _parse_progress_time(payload)
        percent = None
        if total_duration_seconds and total_duration_seconds > 0 and out_time_seconds is not None:
            percent = max(0.0, min((out_time_seconds / total_duration_seconds) * 100.0, 100.0))
        fps = _parse_float(payload.get("fps"))
        speed = _parse_speed(payload.get("speed"))
        return ExecutionProgressUpdate(
            stage="encoding",
            percent=percent,
            out_time_seconds=out_time_seconds,
            fps=fps,
            speed=speed,
            updated_at=datetime.now(timezone.utc),
        )


def _parse_progress_time(payload: dict[str, str]) -> float | None:
    raw_microseconds = payload.get("out_time_us")
    if raw_microseconds:
        try:
            return float(raw_microseconds) / 1_000_000.0
        except ValueError:
            return None
    raw_hms = payload.get("out_time")
    if not raw_hms:
        return None
    try:
        hours, minutes, seconds = raw_hms.split(":")
        return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_speed(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip().lower().removesuffix("x")
    try:
        return float(cleaned)
    except ValueError:
        return None
