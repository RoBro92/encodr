from __future__ import annotations

from pathlib import Path

from encodr_core.config.base import OutputContainer
from encodr_core.media.models import AudioStream, MediaFile, SubtitleStream
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


def has_expected_selected_stream_shape(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    return (
        len(output_media.video_streams) == len(plan.selected_streams.video_stream_indices)
        and len(output_media.audio_streams) == len(plan.selected_streams.audio_stream_indices)
        and len(output_media.subtitle_streams) == len(plan.selected_streams.subtitle_stream_indices)
        and len(output_media.attachment_streams) == len(plan.selected_streams.attachment_stream_indices)
        and len(output_media.data_streams) == len(plan.selected_streams.data_stream_indices)
        and len(output_media.unknown_streams) == len(plan.selected_streams.unknown_stream_indices)
    )


def audio_stream_selection_matches_plan(
    source_media: MediaFile,
    plan: ProcessingPlan,
    output_media: MediaFile,
) -> bool:
    planned_streams = planned_audio_streams(source_media, plan)
    if len(planned_streams) != len(plan.selected_streams.audio_stream_indices):
        return False
    if len(output_media.audio_streams) != len(planned_streams):
        return False
    return all(
        audio_stream_matches(output_stream, planned_stream)
        for output_stream, planned_stream in zip(output_media.audio_streams, planned_streams)
    )


def subtitle_stream_selection_matches_plan(
    source_media: MediaFile,
    plan: ProcessingPlan,
    output_media: MediaFile,
) -> bool:
    planned_streams = planned_subtitle_streams(source_media, plan)
    if len(planned_streams) != len(plan.selected_streams.subtitle_stream_indices):
        return False
    if len(output_media.subtitle_streams) != len(planned_streams):
        return False
    return all(
        subtitle_stream_matches(output_stream, planned_stream)
        for output_stream, planned_stream in zip(output_media.subtitle_streams, planned_streams)
    )


def audio_default_disposition_matches_plan(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if not plan.selected_streams.audio_stream_indices:
        return not any(stream.disposition.default for stream in output_media.audio_streams)
    primary_source_index = (
        plan.audio.primary_stream_index
        if plan.audio.primary_stream_index is not None
        else plan.selected_streams.audio_stream_indices[0]
    )
    try:
        primary_output_index = plan.selected_streams.audio_stream_indices.index(primary_source_index)
    except ValueError:
        return False
    return all(
        stream.disposition.default == (output_index == primary_output_index)
        for output_index, stream in enumerate(output_media.audio_streams)
    )


def subtitle_default_disposition_matches_plan(plan: ProcessingPlan, output_media: MediaFile) -> bool:
    if not plan.selected_streams.subtitle_stream_indices:
        return not any(stream.disposition.default for stream in output_media.subtitle_streams)
    main_source_index = plan.subtitles.main_stream_index
    if main_source_index is None:
        return not any(stream.disposition.default for stream in output_media.subtitle_streams)
    try:
        main_output_index = plan.selected_streams.subtitle_stream_indices.index(main_source_index)
    except ValueError:
        return False
    return all(
        stream.disposition.default == (output_index == main_output_index)
        for output_index, stream in enumerate(output_media.subtitle_streams)
    )


def planned_audio_streams(source_media: MediaFile, plan: ProcessingPlan) -> list[AudioStream]:
    by_index = {stream.index: stream for stream in source_media.audio_streams}
    return [
        by_index[stream_index]
        for stream_index in plan.selected_streams.audio_stream_indices
        if stream_index in by_index
    ]


def planned_subtitle_streams(source_media: MediaFile, plan: ProcessingPlan) -> list[SubtitleStream]:
    by_index = {stream.index: stream for stream in source_media.subtitle_streams}
    return [
        by_index[stream_index]
        for stream_index in plan.selected_streams.subtitle_stream_indices
        if stream_index in by_index
    ]


def audio_stream_matches(output_stream: AudioStream, planned_stream: AudioStream) -> bool:
    return (
        language_code(output_stream.language) == language_code(planned_stream.language)
        and normalised_codec(output_stream.codec_name) == normalised_codec(planned_stream.codec_name)
        and output_stream.channels == planned_stream.channels
    )


def subtitle_stream_matches(output_stream: SubtitleStream, planned_stream: SubtitleStream) -> bool:
    return (
        language_code(output_stream.language) == language_code(planned_stream.language)
        and normalised_codec(output_stream.codec_name) == normalised_codec(planned_stream.codec_name)
        and (output_stream.disposition.forced or output_stream.is_forced)
        == (planned_stream.disposition.forced or planned_stream.is_forced)
    )


def normalised_codec(value: str | None) -> str:
    return (value or "").lower()


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
