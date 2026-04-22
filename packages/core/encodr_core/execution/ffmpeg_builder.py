from __future__ import annotations

from pathlib import Path

from encodr_core.config.base import OutputContainer
from encodr_core.execution.backend_selection import (
    quality_flags_for_backend,
    select_execution_backend,
)
from encodr_core.execution.models import ExecutionCommandPlan
from encodr_core.planning import ProcessingPlan
from encodr_core.planning.enums import PlanAction


def build_execution_command_plan(
    plan: ProcessingPlan,
    *,
    input_path: Path | str,
    scratch_dir: Path | str,
    ffmpeg_path: Path | str = "/usr/bin/ffmpeg",
    job_id: str | None = None,
    preferred_backend: str = "cpu_only",
    allow_cpu_fallback: bool = True,
) -> ExecutionCommandPlan:
    resolved_input = Path(input_path)
    resolved_scratch = Path(scratch_dir)

    if plan.action == PlanAction.SKIP:
        return ExecutionCommandPlan(mode="skip", input_path=resolved_input)
    if plan.action == PlanAction.MANUAL_REVIEW:
        return ExecutionCommandPlan(mode="manual_review", input_path=resolved_input)

    output_path = build_temp_output_path(
        resolved_input,
        scratch_dir=resolved_scratch,
        target_container=plan.container.target_container,
        job_id=job_id,
    )
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(resolved_input),
        "-nostats",
        "-progress",
        "pipe:1",
    ]

    for stream_index in plan.selected_streams.video_stream_indices:
        command.extend(["-map", f"0:{stream_index}"])
    for stream_index in plan.selected_streams.audio_stream_indices:
        command.extend(["-map", f"0:{stream_index}"])
    for stream_index in plan.selected_streams.subtitle_stream_indices:
        command.extend(["-map", f"0:{stream_index}"])
    for stream_index in plan.selected_streams.attachment_stream_indices:
        command.extend(["-map", f"0:{stream_index}"])
    for stream_index in plan.selected_streams.data_stream_indices:
        command.extend(["-map", f"0:{stream_index}"])

    if plan.action == PlanAction.REMUX:
        command.extend(
            [
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "copy",
                "-c:t",
                "copy",
                "-c:d",
                "copy",
            ]
        )
        mode = "remux"
        requested_backend = "cpu"
        actual_backend = "cpu"
        actual_accelerator = "cpu"
        fallback_used = False
        backend_selection_reason = "Remux and strip-only paths use CPU copy operations."
    else:
        backend_selection = select_execution_backend(
            ffmpeg_path=ffmpeg_path,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            target_codec=plan.video.target_codec,
        )
        command[1:1] = backend_selection.command_prefix
        if backend_selection.video_filter:
            command.extend(["-vf", backend_selection.video_filter])
        command.extend(
            [
                "-c:v",
                backend_selection.video_encoder,
                "-c:a",
                "copy",
                "-c:s",
                "copy",
                "-c:t",
                "copy",
                "-c:d",
                "copy",
            ]
        )
        command.extend(
            quality_flags_for_backend(
                accelerator=backend_selection.accelerator,
                quality_mode=plan.video.quality_mode,
            )
        )
        mode = "transcode"
        requested_backend = backend_selection.requested_backend
        actual_backend = backend_selection.actual_backend
        actual_accelerator = backend_selection.accelerator
        fallback_used = backend_selection.fallback_used
        backend_selection_reason = backend_selection.selection_reason

    command.append(str(output_path))
    return ExecutionCommandPlan(
        mode=mode,
        input_path=resolved_input,
        output_path=output_path,
        command=command,
        requested_backend=requested_backend,
        actual_backend=actual_backend,
        actual_accelerator=actual_accelerator,
        fallback_used=fallback_used,
        backend_selection_reason=backend_selection_reason,
    )


def build_temp_output_path(
    input_path: Path,
    *,
    scratch_dir: Path,
    target_container: OutputContainer,
    job_id: str | None = None,
) -> Path:
    suffix = target_container.value
    stem = input_path.stem
    token = job_id or "pending"
    return scratch_dir / f"{stem}.{token}.tmp.{suffix}"
