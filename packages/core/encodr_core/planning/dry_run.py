from __future__ import annotations

from pathlib import Path
from typing import Any

from encodr_core.execution.metrics import estimate_stream_class_sizes
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.planning.enums import PlanAction, VideoHandling


QUALITY_REDUCTION_FACTORS = {
    "high_quality": 0.72,
    "balanced": 0.58,
    "efficient": 0.42,
}


def build_dry_run_analysis_payload(
    media_file: MediaFile,
    plan: ProcessingPlan,
    *,
    ffprobe_path: Path | str | None = None,
) -> dict[str, Any]:
    current_size = media_file.container.size_bytes
    estimated_output_size = estimate_output_size_bytes(
        media_file,
        plan,
        ffprobe_path=ffprobe_path,
    )
    audio_removed_count = len(plan.audio.dropped_stream_indices)
    subtitle_removed_count = len(plan.subtitles.dropped_stream_indices)
    would_trigger_review = plan.action == PlanAction.MANUAL_REVIEW or plan.should_treat_as_protected
    review_reasons = [
        reason.message
        for reason in plan.reasons
        if reason.code.startswith("manual_review_")
    ]
    return {
        "mode": "dry_run",
        "source_path": media_file.file_path.as_posix(),
        "file_name": media_file.file_name,
        "planned_action": plan.action.value,
        "confidence": plan.confidence.value,
        "requires_review": would_trigger_review,
        "is_protected": plan.should_treat_as_protected,
        "reason_codes": [reason.code for reason in plan.reasons],
        "warning_codes": [warning.code for warning in plan.warnings],
        "selected_audio_stream_indices": plan.selected_streams.audio_stream_indices,
        "selected_subtitle_stream_indices": plan.selected_streams.subtitle_stream_indices,
        "output_filename": preview_output_filename(media_file.file_path, plan),
        "current_size_bytes": current_size,
        "estimated_output_size_bytes": estimated_output_size,
        "estimated_space_saved_bytes": (
            max(current_size - estimated_output_size, 0)
            if current_size is not None and estimated_output_size is not None
            else None
        ),
        "audio_tracks_removed_count": audio_removed_count,
        "subtitle_tracks_removed_count": subtitle_removed_count,
        "summary": build_dry_run_summary(
            plan,
            audio_removed_count=audio_removed_count,
            subtitle_removed_count=subtitle_removed_count,
        ),
        "video_handling": describe_video_handling(plan),
        "manual_review_triggered": plan.action == PlanAction.MANUAL_REVIEW,
        "manual_review_reasons": review_reasons,
    }


def estimate_output_size_bytes(
    media_file: MediaFile,
    plan: ProcessingPlan,
    *,
    ffprobe_path: Path | str | None = None,
) -> int | None:
    source_sizes = estimate_stream_class_sizes(media_file, ffprobe_path=ffprobe_path)
    source_video_size = source_sizes["video"]
    source_non_video_size = source_sizes["non_video"]

    selected_audio = {
        stream.index
        for stream in media_file.audio_streams
        if stream.index in plan.audio.selected_stream_indices
    }
    selected_subtitles = {
        stream.index
        for stream in media_file.subtitle_streams
        if stream.index in plan.subtitles.selected_stream_indices
    }
    retained_non_video_size = estimate_stream_class_sizes(
        media_file.model_copy(
            update={
                "audio_streams": [stream for stream in media_file.audio_streams if stream.index in selected_audio],
                "subtitle_streams": [stream for stream in media_file.subtitle_streams if stream.index in selected_subtitles],
            }
        ),
        ffprobe_path=ffprobe_path,
    )["non_video"]
    if retained_non_video_size is None and source_non_video_size is not None:
        dropped_ratio = (
            len(plan.audio.dropped_stream_indices) + len(plan.subtitles.dropped_stream_indices)
        ) / max(len([*media_file.audio_streams, *media_file.subtitle_streams]), 1)
        retained_non_video_size = int(round(source_non_video_size * max(0.0, 1.0 - dropped_ratio)))

    if plan.action == PlanAction.SKIP:
        return media_file.container.size_bytes
    if plan.action in {PlanAction.REMUX, PlanAction.MANUAL_REVIEW}:
        if source_video_size is None and retained_non_video_size is None:
            return media_file.container.size_bytes
        total = 0
        if source_video_size is not None:
            total += source_video_size
        if retained_non_video_size is not None:
            total += retained_non_video_size
        return total or media_file.container.size_bytes

    if not plan.video.transcode_required:
        if source_video_size is None and retained_non_video_size is None:
            return media_file.container.size_bytes
        total = 0
        if source_video_size is not None:
            total += source_video_size
        if retained_non_video_size is not None:
            total += retained_non_video_size
        return total or media_file.container.size_bytes

    if source_video_size is None:
        return None
    reduction_factor = QUALITY_REDUCTION_FACTORS.get(plan.video.quality_mode or "", 0.58)
    estimated_video_size = int(round(source_video_size * reduction_factor))
    total = estimated_video_size + (retained_non_video_size or 0)
    return total or media_file.container.size_bytes


def preview_output_filename(source_path: Path | str, plan: ProcessingPlan) -> str:
    resolved = Path(source_path)
    if plan.replace.in_place:
        return resolved.with_suffix(f".{plan.container.target_container.value}").name
    return resolved.with_name(
        f"{resolved.stem}.encodr.{plan.container.target_container.value}"
    ).name


def build_dry_run_summary(
    plan: ProcessingPlan,
    *,
    audio_removed_count: int,
    subtitle_removed_count: int,
) -> str:
    if plan.action == PlanAction.SKIP:
        return "Already compliant. No media changes would be made."
    if plan.action == PlanAction.MANUAL_REVIEW:
        return "Manual review would be required before Encodr can process this file safely."
    if plan.video.transcode_required:
        return (
            f"Video would be transcoded, with {audio_removed_count} audio track"
            f"{'' if audio_removed_count == 1 else 's'} and {subtitle_removed_count} subtitle track"
            f"{'' if subtitle_removed_count == 1 else 's'} removed."
        )
    return (
        f"Video would be preserved while removing {audio_removed_count} audio track"
        f"{'' if audio_removed_count == 1 else 's'} and {subtitle_removed_count} subtitle track"
        f"{'' if subtitle_removed_count == 1 else 's'}."
    )


def describe_video_handling(plan: ProcessingPlan) -> str:
    if plan.action == PlanAction.MANUAL_REVIEW:
        return "manual_review"
    if plan.action == PlanAction.SKIP:
        return "preserve"
    if plan.video.handling == VideoHandling.TRANSCODE_TO_POLICY or plan.video.transcode_required:
        return "transcode"
    return "strip_only"
