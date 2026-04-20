from enum import StrEnum


class StreamType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    ATTACHMENT = "attachment"
    DATA = "data"
    UNKNOWN = "unknown"


class SubtitleKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    DATA = "data"
    UNKNOWN = "unknown"

