from __future__ import annotations

from pathlib import Path

from encodr_core.config.base import OutputContainer
from encodr_core.execution.models import ExecutionCommandPlan
from encodr_core.planning import ProcessingPlan
from encodr_core.planning.enums import PlanAction

VIDEO_CODEC_MAP = {
    "hevc": "libx265",
    "h264": "libx264",
    "av1": "libaom-av1",
}


def build_execution_command_plan(
    plan: ProcessingPlan,
    *,
    input_path: Path | str,
    scratch_dir: Path | str,
    ffmpeg_path: Path | str = "/usr/bin/ffmpeg",
    job_id: str | None = None,
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
    else:
        codec = VIDEO_CODEC_MAP.get(plan.video.target_codec or "", "libx265")
        command.extend(
            [
                "-c:v",
                codec,
                "-preset",
                "medium",
                "-crf",
                "23",
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
        mode = "transcode"

    command.append(str(output_path))
    return ExecutionCommandPlan(
        mode=mode,
        input_path=resolved_input,
        output_path=output_path,
        command=command,
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
