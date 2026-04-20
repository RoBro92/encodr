from __future__ import annotations

from pathlib import Path
from typing import Any

from encodr_core.media.enums import StreamType, SubtitleKind
from encodr_core.media.models import (
    AttachmentStream,
    AudioStream,
    BaseStream,
    Chapter,
    ContainerFormat,
    DataStream,
    DynamicRangeMetadata,
    MediaFile,
    StreamDisposition,
    StreamTags,
    SubtitleStream,
    UnknownStream,
    VideoStream,
)
from encodr_core.probe.errors import ProbeDataError, ProbeErrorDetail

TEXT_SUBTITLE_CODECS = {
    "subrip",
    "ass",
    "ssa",
    "mov_text",
    "webvtt",
    "text",
    "ttml",
}
IMAGE_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "xsub",
    "dvb_subtitle",
}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def normalise_ffprobe_payload(payload: dict[str, Any], file_path: Path | str) -> MediaFile:
    if not isinstance(payload, dict):
        raise ProbeDataError(
            "Probe payload must be a JSON object.",
            file_path=file_path,
            details=[ProbeErrorDetail(location="root", message="Expected a mapping.")],
        )

    raw_streams = payload.get("streams")
    raw_format = payload.get("format")
    if not isinstance(raw_streams, list):
        raise ProbeDataError(
            "Probe payload is missing a valid streams list.",
            file_path=file_path,
            details=[ProbeErrorDetail(location="streams", message="Expected a list of streams.")],
        )
    if not isinstance(raw_format, dict):
        raise ProbeDataError(
            "Probe payload is missing valid format metadata.",
            file_path=file_path,
            details=[ProbeErrorDetail(location="format", message="Expected a format mapping.")],
        )

    resolved_file_path = Path(raw_format.get("filename") or file_path)
    container = normalise_container(raw_format, resolved_file_path, len(raw_streams))

    video_streams: list[VideoStream] = []
    audio_streams: list[AudioStream] = []
    subtitle_streams: list[SubtitleStream] = []
    attachment_streams: list[AttachmentStream] = []
    data_streams: list[DataStream] = []
    unknown_streams: list[UnknownStream] = []

    for order, stream in enumerate(raw_streams):
        if not isinstance(stream, dict):
            raise ProbeDataError(
                "Probe payload contains a non-mapping stream entry.",
                file_path=resolved_file_path,
                details=[
                    ProbeErrorDetail(
                        location=f"streams[{order}]",
                        message="Expected a stream mapping.",
                    )
                ],
            )

        stream_type = normalise_stream_type(stream.get("codec_type"))
        if stream_type == StreamType.VIDEO:
            video_streams.append(normalise_video_stream(stream, order))
        elif stream_type == StreamType.AUDIO:
            audio_streams.append(normalise_audio_stream(stream, order))
        elif stream_type == StreamType.SUBTITLE:
            subtitle_streams.append(normalise_subtitle_stream(stream, order))
        elif stream_type == StreamType.ATTACHMENT:
            attachment_streams.append(normalise_attachment_stream(stream, order))
        elif stream_type == StreamType.DATA:
            data_streams.append(normalise_data_stream(stream, order))
        else:
            unknown_streams.append(normalise_unknown_stream(stream, order))

    chapters = normalise_chapters(payload.get("chapters", []), resolved_file_path)

    media = MediaFile(
        container=container,
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        attachment_streams=attachment_streams,
        data_streams=data_streams,
        unknown_streams=unknown_streams,
        chapters=chapters,
        raw_format=raw_format,
        is_4k=any(stream.is_4k for stream in video_streams),
        is_hdr_candidate=any(stream.dynamic_range.is_hdr_candidate for stream in video_streams),
        has_english_audio=any(stream.language == "eng" for stream in audio_streams),
        has_forced_english_subtitle=any(
            stream.language == "eng" and stream.is_forced for stream in subtitle_streams
        ),
        has_surround_audio=any(stream.is_surround_candidate for stream in audio_streams),
        has_atmos_capable_audio=any(stream.is_atmos_capable for stream in audio_streams),
    )
    return media


def normalise_container(raw_format: dict[str, Any], file_path: Path, stream_count: int) -> ContainerFormat:
    return ContainerFormat(
        file_path=file_path,
        file_name=file_path.name,
        extension=file_path.suffix.lower().lstrip(".") or None,
        format_name=as_string(raw_format.get("format_name")),
        format_long_name=as_string(raw_format.get("format_long_name")),
        duration_seconds=as_float(raw_format.get("duration")),
        start_time_seconds=as_float(raw_format.get("start_time")),
        bit_rate=as_int(raw_format.get("bit_rate")),
        size_bytes=as_int(raw_format.get("size")),
        probe_score=as_int(raw_format.get("probe_score")),
        stream_count=stream_count,
        tags=normalise_generic_tags(raw_format.get("tags")),
    )


def normalise_video_stream(raw_stream: dict[str, Any], order: int) -> VideoStream:
    dynamic_range = normalise_dynamic_range(raw_stream)
    width = as_int(raw_stream.get("width"))
    height = as_int(raw_stream.get("height"))
    return VideoStream(
        **normalise_base_stream_fields(raw_stream, order, StreamType.VIDEO),
        width=width,
        height=height,
        coded_width=as_int(raw_stream.get("coded_width")),
        coded_height=as_int(raw_stream.get("coded_height")),
        sample_aspect_ratio=as_string(raw_stream.get("sample_aspect_ratio")),
        display_aspect_ratio=as_string(raw_stream.get("display_aspect_ratio")),
        pixel_format=as_string(raw_stream.get("pix_fmt")),
        field_order=as_string(raw_stream.get("field_order")),
        frame_rate=parse_frame_rate(raw_stream.get("r_frame_rate")),
        raw_frame_rate=as_string(raw_stream.get("r_frame_rate")),
        average_frame_rate=parse_frame_rate(raw_stream.get("avg_frame_rate")),
        raw_average_frame_rate=as_string(raw_stream.get("avg_frame_rate")),
        bit_rate=as_int(raw_stream.get("bit_rate")),
        level=as_int(raw_stream.get("level")),
        color_range=as_string(raw_stream.get("color_range")),
        color_space=as_string(raw_stream.get("color_space")),
        color_transfer=as_string(raw_stream.get("color_transfer")),
        color_primaries=as_string(raw_stream.get("color_primaries")),
        chroma_location=as_string(raw_stream.get("chroma_location")),
        bits_per_raw_sample=as_int(raw_stream.get("bits_per_raw_sample")),
        dynamic_range=dynamic_range,
        is_4k=is_4k_resolution(width, height),
    )


def normalise_audio_stream(raw_stream: dict[str, Any], order: int) -> AudioStream:
    tags = normalise_stream_tags(raw_stream.get("tags"))
    disposition = normalise_disposition(raw_stream.get("disposition"))
    text_markers = collect_text_markers(raw_stream, tags)
    channels = as_int(raw_stream.get("channels"))
    channel_layout = as_string(raw_stream.get("channel_layout"))
    return AudioStream(
        **normalise_base_stream_fields(
            raw_stream,
            order,
            StreamType.AUDIO,
            tags=tags,
            disposition=disposition,
        ),
        channels=channels,
        channel_layout=channel_layout,
        sample_rate_hz=as_int(raw_stream.get("sample_rate")),
        bit_rate=as_int(raw_stream.get("bit_rate")),
        is_commentary_candidate=disposition.commentary or contains_any(
            text_markers, ("commentary", "director commentary", "audio commentary")
        ),
        is_surround_candidate=is_surround_audio(channels, channel_layout),
        is_atmos_capable=is_atmos_capable(
            codec_name=as_string(raw_stream.get("codec_name")),
            profile=as_string(raw_stream.get("profile")),
            text_markers=text_markers,
        ),
    )


def normalise_subtitle_stream(raw_stream: dict[str, Any], order: int) -> SubtitleStream:
    tags = normalise_stream_tags(raw_stream.get("tags"))
    disposition = normalise_disposition(raw_stream.get("disposition"))
    text_markers = collect_text_markers(raw_stream, tags)
    return SubtitleStream(
        **normalise_base_stream_fields(
            raw_stream,
            order,
            StreamType.SUBTITLE,
            tags=tags,
            disposition=disposition,
        ),
        subtitle_kind=detect_subtitle_kind(as_string(raw_stream.get("codec_name"))),
        is_forced=disposition.forced or contains_any(text_markers, ("forced",)),
        is_hearing_impaired_candidate=disposition.hearing_impaired
        or contains_any(text_markers, ("sdh", "hearing impaired", "hoh")),
    )


def normalise_attachment_stream(raw_stream: dict[str, Any], order: int) -> AttachmentStream:
    return AttachmentStream(
        **normalise_base_stream_fields(raw_stream, order, StreamType.ATTACHMENT),
    )


def normalise_data_stream(raw_stream: dict[str, Any], order: int) -> DataStream:
    return DataStream(
        **normalise_base_stream_fields(raw_stream, order, StreamType.DATA),
    )


def normalise_unknown_stream(raw_stream: dict[str, Any], order: int) -> UnknownStream:
    return UnknownStream(
        **normalise_base_stream_fields(raw_stream, order, StreamType.UNKNOWN),
    )


def normalise_chapters(raw_chapters: Any, file_path: Path) -> list[Chapter]:
    if raw_chapters in (None, []):
        return []
    if not isinstance(raw_chapters, list):
        raise ProbeDataError(
            "Probe payload contains invalid chapter data.",
            file_path=file_path,
            details=[ProbeErrorDetail(location="chapters", message="Expected a chapter list.")],
        )

    result: list[Chapter] = []
    for index, raw_chapter in enumerate(raw_chapters):
        if not isinstance(raw_chapter, dict):
            raise ProbeDataError(
                "Probe payload contains a non-mapping chapter entry.",
                file_path=file_path,
                details=[
                    ProbeErrorDetail(
                        location=f"chapters[{index}]",
                        message="Expected a chapter mapping.",
                    )
                ],
            )
        tags = normalise_generic_tags(raw_chapter.get("tags"))
        result.append(
            Chapter(
                id=as_int(raw_chapter.get("id")),
                time_base=as_string(raw_chapter.get("time_base")),
                start=as_int(raw_chapter.get("start")),
                start_time=as_float(raw_chapter.get("start_time")),
                end=as_int(raw_chapter.get("end")),
                end_time=as_float(raw_chapter.get("end_time")),
                title=tags.get("title"),
                tags=tags,
            )
        )
    return result


def normalise_base_stream_fields(
    raw_stream: dict[str, Any],
    order: int,
    stream_type: StreamType,
    *,
    tags: StreamTags | None = None,
    disposition: StreamDisposition | None = None,
) -> dict[str, Any]:
    return {
        "index": as_int(raw_stream.get("index")) if raw_stream.get("index") is not None else order,
        "stream_order": order,
        "stream_type": stream_type,
        "codec_name": as_string(raw_stream.get("codec_name")),
        "codec_long_name": as_string(raw_stream.get("codec_long_name")),
        "profile": as_string(raw_stream.get("profile")),
        "codec_tag_string": as_string(raw_stream.get("codec_tag_string")),
        "codec_tag": as_string(raw_stream.get("codec_tag")),
        "tags": tags or normalise_stream_tags(raw_stream.get("tags")),
        "disposition": disposition or normalise_disposition(raw_stream.get("disposition")),
        "raw_stream": raw_stream,
    }


def normalise_stream_type(value: Any) -> StreamType:
    text = as_string(value)
    if text is None:
        return StreamType.UNKNOWN
    lowered = text.lower()
    for stream_type in StreamType:
        if lowered == stream_type.value:
            return stream_type
    return StreamType.UNKNOWN


def normalise_stream_tags(raw_tags: Any) -> StreamTags:
    tags = normalise_generic_tags(raw_tags)
    lowered_map = {key.lower(): value for key, value in tags.items()}
    language = lowered_map.get("language")
    if language:
        language = language.lower()
    return StreamTags(
        language=language,
        title=lowered_map.get("title"),
        handler_name=lowered_map.get("handler_name"),
        vendor_id=lowered_map.get("vendor_id"),
        mimetype=lowered_map.get("mimetype"),
        filename=lowered_map.get("filename"),
        raw=tags,
    )


def normalise_generic_tags(raw_tags: Any) -> dict[str, str]:
    if not isinstance(raw_tags, dict):
        return {}
    normalised: dict[str, str] = {}
    for key, value in raw_tags.items():
        if key is None or value is None:
            continue
        normalised[str(key)] = str(value).strip()
    return normalised


def normalise_disposition(raw_disposition: Any) -> StreamDisposition:
    if not isinstance(raw_disposition, dict):
        return StreamDisposition()

    raw_flags = {
        str(key): bool(as_int(value) or False) if not isinstance(value, bool) else value
        for key, value in raw_disposition.items()
    }
    return StreamDisposition(
        default=raw_flags.get("default", False),
        dub=raw_flags.get("dub", False),
        original=raw_flags.get("original", False),
        commentary=raw_flags.get("comment", False) or raw_flags.get("commentary", False),
        lyrics=raw_flags.get("lyrics", False),
        karaoke=raw_flags.get("karaoke", False),
        forced=raw_flags.get("forced", False),
        hearing_impaired=raw_flags.get("hearing_impaired", False),
        visual_impaired=raw_flags.get("visual_impaired", False),
        clean_effects=raw_flags.get("clean_effects", False),
        attached_pic=raw_flags.get("attached_pic", False),
        timed_thumbnails=raw_flags.get("timed_thumbnails", False),
        captions=raw_flags.get("captions", False),
        descriptions=raw_flags.get("descriptions", False),
        metadata=raw_flags.get("metadata", False),
        dependent=raw_flags.get("dependent", False),
        still_image=raw_flags.get("still_image", False),
        raw=raw_flags,
    )


def normalise_dynamic_range(raw_stream: dict[str, Any]) -> DynamicRangeMetadata:
    color_transfer = as_string(raw_stream.get("color_transfer"))
    side_data_list = raw_stream.get("side_data_list")
    side_data_types: list[str] = []
    if isinstance(side_data_list, list):
        for item in side_data_list:
            if isinstance(item, dict):
                side_data_type = as_string(item.get("side_data_type"))
                if side_data_type:
                    side_data_types.append(side_data_type)

    joined_side_data = " ".join(side_data_types).lower()
    hdr_candidate = bool(
        color_transfer in HDR_TRANSFERS
        or "mastering display metadata" in joined_side_data
        or "content light level metadata" in joined_side_data
        or "dovi configuration record" in joined_side_data
    )
    dv_candidate = "dovi configuration record" in joined_side_data

    hdr_format: str | None = None
    if dv_candidate:
        hdr_format = "dolby_vision"
    elif color_transfer == "smpte2084":
        hdr_format = "hdr10_pq"
    elif color_transfer == "arib-std-b67":
        hdr_format = "hlg"

    return DynamicRangeMetadata(
        is_hdr_candidate=hdr_candidate,
        is_dolby_vision_candidate=dv_candidate,
        side_data_types=side_data_types,
        mastering_display_metadata_present="mastering display metadata" in joined_side_data,
        content_light_metadata_present="content light level metadata" in joined_side_data,
        dolby_vision_metadata_present=dv_candidate,
        hdr_format=hdr_format,
    )


def detect_subtitle_kind(codec_name: str | None) -> SubtitleKind:
    if codec_name is None:
        return SubtitleKind.UNKNOWN
    lowered = codec_name.lower()
    if lowered in TEXT_SUBTITLE_CODECS:
        return SubtitleKind.TEXT
    if lowered in IMAGE_SUBTITLE_CODECS:
        return SubtitleKind.IMAGE
    if "teletext" in lowered or "dvb" in lowered:
        return SubtitleKind.DATA
    return SubtitleKind.UNKNOWN


def collect_text_markers(raw_stream: dict[str, Any], tags: StreamTags) -> str:
    parts = [
        as_string(raw_stream.get("profile")) or "",
        tags.title or "",
        tags.handler_name or "",
        " ".join(tags.raw.values()),
    ]
    return " ".join(parts).lower()


def is_4k_resolution(width: int | None, height: int | None) -> bool:
    if width is None and height is None:
        return False
    return bool((width and width >= 3840) or (height and height >= 2160))


def is_surround_audio(channels: int | None, channel_layout: str | None) -> bool:
    if channels is not None and channels >= 6:
        return True
    if channel_layout:
        layout = channel_layout.lower()
        return any(marker in layout for marker in ("5.1", "7.1", "6.1"))
    return False


def is_atmos_capable(codec_name: str | None, profile: str | None, text_markers: str) -> bool:
    markers = " ".join(filter(None, [codec_name, profile, text_markers])).lower()
    if "atmos" in markers:
        return True
    if codec_name in {"truehd", "eac3"} and "joc" in markers:
        return True
    return False


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def parse_frame_rate(value: Any) -> float | None:
    text = as_string(value)
    if text is None or text in {"0/0", "N/A"}:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        numerator_value = as_float(numerator)
        denominator_value = as_float(denominator)
        if numerator_value is None or denominator_value in (None, 0.0):
            return None
        return numerator_value / denominator_value
    return as_float(text)


def as_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None

