from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from encodr_core.config.base import ConfigModel


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class VerificationCheck(ConfigModel):
    code: str
    message: str
    passed: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationIssue(ConfigModel):
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationOutputSummary(ConfigModel):
    file_path: Path
    container: str | None = None
    video_stream_count: int = 0
    audio_stream_count: int = 0
    subtitle_stream_count: int = 0
    is_4k: bool = False
    has_english_audio: bool = False
    has_forced_english_subtitle: bool = False
    has_surround_audio: bool = False
    has_atmos_capable_audio: bool = False
    primary_video_codec: str | None = None
    primary_audio_codec: str | None = None


class VerificationResult(ConfigModel):
    status: VerificationStatus
    passed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)
    warnings: list[VerificationIssue] = Field(default_factory=list)
    failures: list[VerificationIssue] = Field(default_factory=list)
    output_summary: VerificationOutputSummary | None = None

    @classmethod
    def not_required(cls) -> "VerificationResult":
        return cls(
            status=VerificationStatus.NOT_REQUIRED,
            passed=True,
        )
