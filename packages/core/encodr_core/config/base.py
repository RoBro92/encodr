from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{3}$", min_length=3, max_length=3)]
NonEmptyString = Annotated[str, Field(min_length=1)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
FilesystemPath = Path


class ConfigModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class EnvironmentName(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class SessionMode(StrEnum):
    JWT = "jwt"
    SERVER_SESSION = "server_session"


class OutputContainer(StrEnum):
    MKV = "mkv"
    MP4 = "mp4"


class PolicyDecision(StrEnum):
    SKIP = "skip"
    REMUX = "remux"
    TRANSCODE = "transcode"


class VideoCodec(StrEnum):
    H264 = "h264"
    HEVC = "hevc"
    AV1 = "av1"
    MPEG2 = "mpeg2"
    VP9 = "vp9"


class FourKMode(StrEnum):
    STRIP_ONLY = "strip_only"
    POLICY_CONTROLLED = "policy_controlled"


class WorkerType(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class RemoteWorkerAuthMode(StrEnum):
    NONE = "none"
    TOKEN = "token"
    MTLS = "mtls"

    @classmethod
    def normalise(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


def deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


class LanguageListModel(ConfigModel):
    @field_validator("*", mode="before")
    @classmethod
    def normalise_language_lists(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [item.strip().lower() if isinstance(item, str) else item for item in value]
        return value
