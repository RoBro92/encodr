from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import Field

from encodr_core.config.base import ConfigModel
from encodr_core.replacement.service import ReplacementResult
from encodr_core.verification.models import VerificationResult


class ExecutionCommandPlan(ConfigModel):
    mode: str
    input_path: Path
    output_path: Path | None = None
    command: list[str] = Field(default_factory=list)
    requested_backend: str | None = None
    actual_backend: str | None = None
    actual_accelerator: str | None = None
    fallback_used: bool = False
    backend_selection_reason: str | None = None


class ExecutionResult(ConfigModel):
    mode: str
    status: str
    command: list[str] = Field(default_factory=list)
    output_path: Path | None = None
    final_output_path: Path | None = None
    original_backup_path: Path | None = None
    input_size_bytes: int | None = None
    output_size_bytes: int | None = None
    space_saved_bytes: int | None = None
    video_input_size_bytes: int | None = None
    video_output_size_bytes: int | None = None
    video_space_saved_bytes: int | None = None
    non_video_space_saved_bytes: int | None = None
    compression_reduction_percent: float | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    failure_message: str | None = None
    failure_category: str | None = None
    requested_backend: str | None = None
    actual_backend: str | None = None
    actual_accelerator: str | None = None
    backend_fallback_used: bool = False
    backend_selection_reason: str | None = None
    analysis_payload: dict | None = None
    verification: VerificationResult | None = None
    replacement: ReplacementResult | None = None
    started_at: datetime
    completed_at: datetime


class ExecutionProgressUpdate(ConfigModel):
    stage: str
    percent: float | None = None
    out_time_seconds: float | None = None
    fps: float | None = None
    speed: float | None = None
    updated_at: datetime
