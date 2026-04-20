from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

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
