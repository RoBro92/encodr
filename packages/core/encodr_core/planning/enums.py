from enum import StrEnum


class PlanAction(StrEnum):
    SKIP = "skip"
    REMUX = "remux"
    TRANSCODE = "transcode"
    MANUAL_REVIEW = "manual_review"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VideoHandling(StrEnum):
    PRESERVE = "preserve"
    TRANSCODE_TO_POLICY = "transcode_to_policy"


class ContainerHandling(StrEnum):
    PRESERVE = "preserve"
    REMUX_TO_TARGET = "remux_to_target"


class RenameTemplateKind(StrEnum):
    MOVIE = "movie"
    EPISODE = "episode"
    GENERIC = "generic"


class RenameTemplateSource(StrEnum):
    POLICY = "policy"
    PROFILE = "profile"
    DISABLED = "disabled"

