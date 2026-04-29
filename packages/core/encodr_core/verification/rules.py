from __future__ import annotations

from pathlib import Path

from encodr_core.config.base import OutputContainer
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan


def output_container_matches(media_file: MediaFile, target_container: OutputContainer) -> bool:
    if media_file.extension == target_container.value:
        return True
    format_name = media_file.container.format_name or ""
    return target_container.value in format_name.split(",")


def has_required_audio(plan: ProcessingPlan, media_file: MediaFile) -> bool:
    if not plan.audio.selected_stream_indices:
        return True
    required_languages = plan.audio.required_language_codes
    if not required_languages:
        return media_file.has_english_audio
    output_languages = {language_code(stream.language) for stream in media_file.audio_streams}
    return all(language in output_languages for language in required_languages)


def has_required_english_audio(plan: ProcessingPlan, media_file: MediaFile) -> bool:
    return has_required_audio(plan, media_file)


def has_required_subtitles(plan: ProcessingPlan, media_file: MediaFile) -> bool:
    if not plan.subtitles.selected_stream_indices:
        return True
    if not media_file.subtitle_streams:
        return False
    subtitle_languages = {language_code(stream.language) for stream in media_file.subtitle_streams}
    if plan.subtitles.required_language_codes:
        if not all(language in subtitle_languages for language in plan.subtitles.required_language_codes):
            return False
    if plan.subtitles.forced_stream_indices:
        if plan.subtitles.required_forced_language_codes:
            forced_languages = {
                language_code(stream.language)
                for stream in media_file.subtitle_streams
                if stream.disposition.forced or stream.is_forced
            }
            return all(language in forced_languages for language in plan.subtitles.required_forced_language_codes)
        return media_file.has_forced_english_subtitle
    if plan.subtitles.required_language_codes:
        return True
    return "eng" in subtitle_languages


def has_required_video(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if plan.video.primary_stream_index is None:
        return True
    if not output_media.video_streams:
        return False
    if not plan.video.transcode_required or plan.video.target_codec is None:
        return True
    return output_media.video_streams[0].codec_name == plan.video.target_codec


def retains_required_4k(source_media: MediaFile, plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if not source_media.is_4k:
        return True
    if not plan.video.preserve_original:
        return True
    return output_media.is_4k


def retains_required_surround(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if not plan.audio.preserved_surround_stream_indices:
        return True
    return output_media.has_surround_audio


def retains_required_atmos(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if not plan.audio.preserved_atmos_stream_indices:
        return True
    return output_media.has_atmos_capable_audio


def is_non_empty_output(file_path: Path) -> bool:
    return file_path.exists() and file_path.is_file() and file_path.stat().st_size > 0


def language_code(value: str | None) -> str:
    return value or "und"
