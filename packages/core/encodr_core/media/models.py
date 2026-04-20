from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from encodr_core.media.enums import StreamType, SubtitleKind


class MediaModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=False,
    )


class StreamDisposition(MediaModel):
    default: bool = False
    dub: bool = False
    original: bool = False
    commentary: bool = False
    lyrics: bool = False
    karaoke: bool = False
    forced: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    clean_effects: bool = False
    attached_pic: bool = False
    timed_thumbnails: bool = False
    captions: bool = False
    descriptions: bool = False
    metadata: bool = False
    dependent: bool = False
    still_image: bool = False
    raw: dict[str, bool] = Field(default_factory=dict)


class StreamTags(MediaModel):
    language: str | None = None
    title: str | None = None
    handler_name: str | None = None
    vendor_id: str | None = None
    mimetype: str | None = None
    filename: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)


class DynamicRangeMetadata(MediaModel):
    is_hdr_candidate: bool = False
    is_dolby_vision_candidate: bool = False
    side_data_types: list[str] = Field(default_factory=list)
    mastering_display_metadata_present: bool = False
    content_light_metadata_present: bool = False
    dolby_vision_metadata_present: bool = False
    hdr_format: str | None = None


class BaseStream(MediaModel):
    index: int
    stream_order: int
    stream_type: StreamType
    codec_name: str | None = None
    codec_long_name: str | None = None
    profile: str | None = None
    codec_tag_string: str | None = None
    codec_tag: str | None = None
    tags: StreamTags = Field(default_factory=StreamTags)
    disposition: StreamDisposition = Field(default_factory=StreamDisposition)
    raw_stream: dict[str, Any] = Field(default_factory=dict)

    @property
    def language(self) -> str | None:
        return self.tags.language

    @property
    def title(self) -> str | None:
        return self.tags.title


class VideoStream(BaseStream):
    stream_type: StreamType = StreamType.VIDEO
    width: int | None = None
    height: int | None = None
    coded_width: int | None = None
    coded_height: int | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    pixel_format: str | None = None
    field_order: str | None = None
    frame_rate: float | None = None
    raw_frame_rate: str | None = None
    average_frame_rate: float | None = None
    raw_average_frame_rate: str | None = None
    bit_rate: int | None = None
    level: int | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    chroma_location: str | None = None
    bits_per_raw_sample: int | None = None
    dynamic_range: DynamicRangeMetadata = Field(default_factory=DynamicRangeMetadata)
    is_4k: bool = False


class AudioStream(BaseStream):
    stream_type: StreamType = StreamType.AUDIO
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate_hz: int | None = None
    bit_rate: int | None = None
    is_commentary_candidate: bool = False
    is_surround_candidate: bool = False
    is_atmos_capable: bool = False


class SubtitleStream(BaseStream):
    stream_type: StreamType = StreamType.SUBTITLE
    subtitle_kind: SubtitleKind = SubtitleKind.UNKNOWN
    is_forced: bool = False
    is_hearing_impaired_candidate: bool = False


class AttachmentStream(BaseStream):
    stream_type: StreamType = StreamType.ATTACHMENT


class DataStream(BaseStream):
    stream_type: StreamType = StreamType.DATA


class UnknownStream(BaseStream):
    stream_type: StreamType = StreamType.UNKNOWN


class Chapter(MediaModel):
    id: int | None = None
    time_base: str | None = None
    start: int | None = None
    start_time: float | None = None
    end: int | None = None
    end_time: float | None = None
    title: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ContainerFormat(MediaModel):
    file_path: Path
    file_name: str
    extension: str | None = None
    format_name: str | None = None
    format_long_name: str | None = None
    duration_seconds: float | None = None
    start_time_seconds: float | None = None
    bit_rate: int | None = None
    size_bytes: int | None = None
    probe_score: int | None = None
    stream_count: int
    tags: dict[str, str] = Field(default_factory=dict)


class MediaFile(MediaModel):
    container: ContainerFormat
    video_streams: list[VideoStream] = Field(default_factory=list)
    audio_streams: list[AudioStream] = Field(default_factory=list)
    subtitle_streams: list[SubtitleStream] = Field(default_factory=list)
    attachment_streams: list[AttachmentStream] = Field(default_factory=list)
    data_streams: list[DataStream] = Field(default_factory=list)
    unknown_streams: list[UnknownStream] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    raw_format: dict[str, Any] = Field(default_factory=dict)
    is_4k: bool = False
    is_hdr_candidate: bool = False
    has_english_audio: bool = False
    has_forced_english_subtitle: bool = False
    has_surround_audio: bool = False
    has_atmos_capable_audio: bool = False

    @property
    def file_path(self) -> Path:
        return self.container.file_path

    @property
    def file_name(self) -> str:
        return self.container.file_name

    @property
    def extension(self) -> str | None:
        return self.container.extension

