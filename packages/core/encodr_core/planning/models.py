from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from encodr_core.config.base import ConfigModel, OutputContainer
from encodr_core.planning.enums import (
    ConfidenceLevel,
    ContainerHandling,
    PlanAction,
    RenameTemplateKind,
    RenameTemplateSource,
    VideoHandling,
)


class PlanReason(ConfigModel):
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanWarning(ConfigModel):
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectedStreamSet(ConfigModel):
    video_stream_indices: list[int] = Field(default_factory=list)
    audio_stream_indices: list[int] = Field(default_factory=list)
    subtitle_stream_indices: list[int] = Field(default_factory=list)
    attachment_stream_indices: list[int] = Field(default_factory=list)
    data_stream_indices: list[int] = Field(default_factory=list)
    unknown_stream_indices: list[int] = Field(default_factory=list)


class AudioSelectionIntent(ConfigModel):
    selected_stream_indices: list[int] = Field(default_factory=list)
    dropped_stream_indices: list[int] = Field(default_factory=list)
    primary_stream_index: int | None = None
    preserved_atmos_stream_indices: list[int] = Field(default_factory=list)
    preserved_surround_stream_indices: list[int] = Field(default_factory=list)
    commentary_removed_stream_indices: list[int] = Field(default_factory=list)
    available_preferred_language_stream_indices: list[int] = Field(default_factory=list)
    missing_required_audio: bool = False


class SubtitleSelectionIntent(ConfigModel):
    selected_stream_indices: list[int] = Field(default_factory=list)
    dropped_stream_indices: list[int] = Field(default_factory=list)
    forced_stream_indices: list[int] = Field(default_factory=list)
    main_stream_index: int | None = None
    hearing_impaired_stream_indices: list[int] = Field(default_factory=list)
    ambiguous_forced_stream_indices: list[int] = Field(default_factory=list)


class VideoPlan(ConfigModel):
    primary_stream_index: int | None = None
    handling: VideoHandling
    preserve_original: bool
    target_codec: str | None = None
    transcode_required: bool = False


class ContainerPlan(ConfigModel):
    source_extension: str | None = None
    target_container: OutputContainer
    handling: ContainerHandling
    change_required: bool = False


class RenamePlan(ConfigModel):
    enabled: bool
    template_kind: RenameTemplateKind | None = None
    template_source: RenameTemplateSource = RenameTemplateSource.DISABLED
    template_value: str | None = None


class ReplacePlan(ConfigModel):
    in_place: bool
    require_verification: bool
    keep_original_until_verified: bool
    delete_replaced_source: bool


class PolicyContext(ConfigModel):
    policy_name: str
    policy_version: int
    selected_profile_name: str | None = None
    selected_profile_description: str | None = None
    matched_path_prefix: str | None = None
    source_path: Path


class PlanSummary(ConfigModel):
    action: PlanAction
    confidence: ConfidenceLevel
    is_already_compliant: bool
    should_treat_as_protected: bool


class ProcessingPlan(ConfigModel):
    action: PlanAction
    summary: PlanSummary
    policy_context: PolicyContext
    selected_streams: SelectedStreamSet
    audio: AudioSelectionIntent
    subtitles: SubtitleSelectionIntent
    video: VideoPlan
    container: ContainerPlan
    rename: RenamePlan
    replace: ReplacePlan
    reasons: list[PlanReason] = Field(default_factory=list)
    warnings: list[PlanWarning] = Field(default_factory=list)
    confidence: ConfidenceLevel
    is_already_compliant: bool
    should_treat_as_protected: bool

