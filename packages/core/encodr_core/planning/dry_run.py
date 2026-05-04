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
        "reason_messages": [reason.message for reason in plan.reasons],
        "warning_codes": [warning.code for warning in plan.warnings],
        "warning_messages": [warning.message for warning in plan.warnings],
        "selected_audio_stream_indices": plan.selected_streams.audio_stream_indices,
        "selected_subtitle_stream_indices": plan.selected_streams.subtitle_stream_indices,
        "audio_stream_decisions": build_audio_stream_decisions(media_file, plan),
        "subtitle_stream_decisions": build_subtitle_stream_decisions(media_file, plan),
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
        "source_video_bitrate_bps": plan.video.source_bitrate_bps,
        "estimated_output_video_bitrate_bps": estimate_output_video_bitrate_bps(plan),
        "target_crf": plan.video.quality_crf,
        "low_bitrate_skip_threshold_bps": plan.video.low_bitrate_skip_threshold_bps,
        "minimum_output_bitrate_bps": plan.video.minimum_output_bitrate_bps,
        "max_allowed_video_reduction_percent": plan.video.max_allowed_video_reduction_percent,
        "output_larger_than_input_review_percent": plan.video.output_larger_than_input_review_percent,
        "manual_review_triggered": plan.action == PlanAction.MANUAL_REVIEW,
        "manual_review_reasons": review_reasons,
    }


def build_audio_stream_decisions(media_file: MediaFile, plan: ProcessingPlan) -> list[dict[str, Any]]:
    selected = set(plan.audio.selected_stream_indices)
    available_preferred = set(plan.audio.available_preferred_language_stream_indices)
    commentary_removed = set(plan.audio.commentary_removed_stream_indices)
    decisions: list[dict[str, Any]] = []
    for stream in media_file.audio_streams:
        selected_stream = stream.index in selected
        role = audio_stream_role(stream.index, plan)
        decisions.append(
            {
                "index": stream.index,
                "language": language_code(stream.language),
                "codec": stream.codec_name,
                "channels": stream.channels,
                "channel_layout": stream.channel_layout,
                "title": stream.title,
                "default": stream.disposition.default,
                "commentary": stream.is_commentary_candidate,
                "selected": selected_stream,
                "role": role,
                "reason": audio_stream_decision_reason(
                    stream.index,
                    selected_stream=selected_stream,
                    role=role,
                    available_preferred=available_preferred,
                    commentary_removed=commentary_removed,
                ),
            }
        )
    return decisions


def build_subtitle_stream_decisions(media_file: MediaFile, plan: ProcessingPlan) -> list[dict[str, Any]]:
    selected = set(plan.subtitles.selected_stream_indices)
    required_languages = set(plan.subtitles.required_language_codes)
    decisions: list[dict[str, Any]] = []
    for stream in media_file.subtitle_streams:
        selected_stream = stream.index in selected
        role = subtitle_stream_role(stream.index, plan)
        decisions.append(
            {
                "index": stream.index,
                "language": language_code(stream.language),
                "codec": stream.codec_name,
                "title": stream.title,
                "default": stream.disposition.default,
                "forced": stream.disposition.forced or stream.is_forced,
                "hearing_impaired": stream.is_hearing_impaired_candidate,
                "selected": selected_stream,
                "role": role,
                "reason": subtitle_stream_decision_reason(
                    stream.index,
                    language=language_code(stream.language),
                    selected_stream=selected_stream,
                    role=role,
                    required_languages=required_languages,
                ),
            }
        )
    return decisions


def audio_stream_role(stream_index: int, plan: ProcessingPlan) -> str:
    if stream_index == plan.audio.primary_stream_index:
        return "primary"
    if stream_index in plan.audio.preserved_atmos_stream_indices:
        return "atmos"
    if stream_index in plan.audio.preserved_surround_stream_indices:
        return "surround"
    if stream_index in plan.audio.selected_stream_indices:
        return "preferred"
    return "removed"


def audio_stream_decision_reason(
    stream_index: int,
    *,
    selected_stream: bool,
    role: str,
    available_preferred: set[int],
    commentary_removed: set[int],
) -> str:
    if selected_stream and role == "primary":
        return "primary_preferred_audio"
    if selected_stream and role == "atmos":
        return "atmos_audio_preserved"
    if selected_stream and role == "surround":
        return "surround_audio_preserved"
    if selected_stream:
        return "preferred_audio_selected"
    if stream_index in commentary_removed:
        return "commentary_audio_removed"
    if stream_index in available_preferred:
        return "spare_preferred_audio_removed"
    return "non_preferred_audio_removed"


def subtitle_stream_role(stream_index: int, plan: ProcessingPlan) -> str:
    if stream_index in plan.subtitles.forced_stream_indices:
        return "forced"
    if stream_index == plan.subtitles.main_stream_index:
        return "primary"
    if stream_index in plan.subtitles.hearing_impaired_stream_indices:
        return "hearing_impaired"
    if stream_index in plan.subtitles.selected_stream_indices:
        return "preferred"
    return "removed"


def subtitle_stream_decision_reason(
    stream_index: int,
    *,
    language: str,
    selected_stream: bool,
    role: str,
    required_languages: set[str],
) -> str:
    if selected_stream and role == "forced":
        return "forced_subtitle_preserved"
    if selected_stream and role == "primary":
        return "primary_preferred_subtitle"
    if selected_stream and role == "hearing_impaired":
        return "hearing_impaired_subtitle_preserved"
    if selected_stream:
        return "preferred_subtitle_selected"
    if language in required_languages:
        return "spare_preferred_subtitle_removed"
    return "non_preferred_subtitle_removed"


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


def estimate_output_video_bitrate_bps(plan: ProcessingPlan) -> int | None:
    if plan.video.source_bitrate_bps is None:
        return None
    if not plan.video.transcode_required:
        return plan.video.source_bitrate_bps
    reduction_factor = QUALITY_REDUCTION_FACTORS.get(plan.video.quality_mode or "", 0.58)
    return int(round(plan.video.source_bitrate_bps * reduction_factor))


def language_code(value: str | None) -> str:
    return value or "und"
