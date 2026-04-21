from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.plans import PlanSnapshotDetailResponse, ProbeSnapshotDetailResponse
from encodr_db.models import TrackedFile


class FilePathRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_path must not be empty.")
        return cleaned


class FileSelectionRequest(BaseModel):
    source_path: str | None = None
    folder_path: str | None = None
    selected_paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self) -> "FileSelectionRequest":
        provided = sum(
            bool(value)
            for value in [
                self.source_path and self.source_path.strip(),
                self.folder_path and self.folder_path.strip(),
                self.selected_paths,
            ]
        )
        if provided != 1:
            raise ValueError("Provide exactly one of source_path, folder_path, or selected_paths.")
        return self


class FolderBrowseEntryResponse(BaseModel):
    name: str
    path: str
    entry_type: str
    is_video: bool


class FolderBrowseResponse(BaseModel):
    root_path: str
    current_path: str
    parent_path: str | None = None
    entries: list[FolderBrowseEntryResponse]


class FolderScanSummaryResponse(BaseModel):
    folder_path: str
    root_path: str
    directory_count: int
    direct_directory_count: int
    video_file_count: int
    likely_show_count: int
    likely_season_count: int
    likely_episode_count: int
    likely_film_count: int
    files: list[FolderBrowseEntryResponse]


class DryRunItemResponse(BaseModel):
    source_path: str
    file_name: str
    action: str
    confidence: str
    requires_review: bool
    is_protected: bool
    reason_codes: list[str]
    warning_codes: list[str]
    selected_audio_stream_indices: list[int]
    selected_subtitle_stream_indices: list[int]


class DryRunBatchResponse(BaseModel):
    mode: str = "dry_run"
    scope: str
    total_files: int
    protected_count: int
    review_count: int
    actions: list[dict[str, int | str]]
    items: list[DryRunItemResponse]


class BatchPlanItemResponse(BaseModel):
    tracked_file: TrackedFileSummaryResponse
    latest_probe_snapshot: ProbeSnapshotDetailResponse
    latest_plan_snapshot: PlanSnapshotDetailResponse


class BatchPlanResponse(BaseModel):
    scope: str
    total_files: int
    actions: list[dict[str, int | str]]
    items: list[BatchPlanItemResponse]


class TrackedFileSummaryResponse(BaseModel):
    id: str
    source_path: str
    source_filename: str
    source_extension: str | None = None
    source_directory: str
    last_observed_size: int | None = None
    last_observed_modified_time: datetime | None = None
    fingerprint_placeholder: str | None = None
    is_4k: bool
    lifecycle_state: str
    compliance_state: str
    is_protected: bool
    operator_protected: bool = False
    protected_source: str | None = None
    operator_protected_note: str | None = None
    requires_review: bool = False
    review_status: str | None = None
    last_processed_policy_version: int | None = None
    last_processed_profile_name: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, tracked_file: TrackedFile) -> "TrackedFileSummaryResponse":
        return cls(
            id=tracked_file.id,
            source_path=tracked_file.source_path,
            source_filename=tracked_file.source_filename,
            source_extension=tracked_file.source_extension,
            source_directory=tracked_file.source_directory,
            last_observed_size=tracked_file.last_observed_size,
            last_observed_modified_time=tracked_file.last_observed_modified_time,
            fingerprint_placeholder=tracked_file.fingerprint_placeholder,
            is_4k=tracked_file.is_4k,
            lifecycle_state=tracked_file.lifecycle_state.value,
            compliance_state=tracked_file.compliance_state.value,
            is_protected=tracked_file.is_protected,
            operator_protected=tracked_file.operator_protected,
            protected_source=(
                "operator"
                if tracked_file.operator_protected
                else ("planner" if tracked_file.is_protected else None)
            ),
            operator_protected_note=tracked_file.operator_protected_note,
            requires_review=(
                tracked_file.lifecycle_state.value == "manual_review"
                or tracked_file.compliance_state.value == "manual_review"
                or tracked_file.is_protected
            ),
            review_status=(
                "open"
                if (
                    tracked_file.lifecycle_state.value == "manual_review"
                    or tracked_file.compliance_state.value == "manual_review"
                    or tracked_file.is_protected
                )
                else None
            ),
            last_processed_policy_version=tracked_file.last_processed_policy_version,
            last_processed_profile_name=tracked_file.last_processed_profile_name,
            created_at=tracked_file.created_at,
            updated_at=tracked_file.updated_at,
        )


class TrackedFileDetailResponse(TrackedFileSummaryResponse):
    latest_probe_snapshot_id: str | None = None
    latest_plan_snapshot_id: str | None = None


class FileListResponse(BaseModel):
    items: list[TrackedFileSummaryResponse]
    limit: int | None = None
    offset: int = 0


class ProbeFileResponse(BaseModel):
    tracked_file: TrackedFileSummaryResponse
    latest_probe_snapshot: ProbeSnapshotDetailResponse


class PlanFileResponse(BaseModel):
    tracked_file: TrackedFileSummaryResponse
    latest_probe_snapshot: ProbeSnapshotDetailResponse
    latest_plan_snapshot: PlanSnapshotDetailResponse


BatchPlanItemResponse.model_rebuild()
