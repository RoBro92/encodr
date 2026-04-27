from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.worker import (
    DevicePathStatusResponse,
    ExecutionBackendStatusResponse,
    ExecutionPreferenceResponse,
    HealthStatus,
    QueueHealthSummaryResponse,
)


class PathStatusResponse(BaseModel):
    role: str
    display_name: str
    path: str
    status: HealthStatus
    issue_code: str
    message: str
    recommended_action: str | None = None
    exists: bool
    is_directory: bool
    is_mount: bool
    readable: bool
    writable: bool
    same_filesystem_as_root: bool | None = None
    entry_count: int | None = None
    total_space_bytes: int | None = None
    free_space_bytes: int | None = None
    free_space_ratio: float | None = None


class StorageStatusResponse(BaseModel):
    status: HealthStatus
    summary: str
    standard_media_root: str
    scratch: PathStatusResponse
    data_dir: PathStatusResponse
    media_mounts: list[PathStatusResponse]
    warnings: list[str]


class RuntimeStatusResponse(BaseModel):
    status: HealthStatus
    summary: str
    version: str
    environment: str
    db_reachable: bool
    schema_reachable: bool
    auth_enabled: bool
    api_base_path: str
    standard_media_root: str
    scratch_dir: str
    data_dir: str
    media_mounts: list[str]
    local_worker_enabled: bool
    first_user_setup_required: bool
    storage_setup_incomplete: bool
    user_count: int | None = None
    config_sources: dict[str, str]
    warnings: list[str]
    execution_backends: list[ExecutionBackendStatusResponse]
    runtime_device_paths: list[DevicePathStatusResponse]
    execution_preferences: ExecutionPreferenceResponse
    queue_health: QueueHealthSummaryResponse


class UpdateStatusResponse(BaseModel):
    current_version: str
    latest_version: str | None = None
    update_available: bool
    channel: str
    status: str
    release_name: str | None = None
    release_summary: str | None = None
    breaking_changes_summary: str | None = None
    checked_at: str | None = None
    error: str | None = None
    download_url: str | None = None
    release_notes_url: str | None = None


class DiagnosticLogEventResponse(BaseModel):
    timestamp: str
    level: str
    component: str
    logger: str
    message: str
    fields: dict = Field(default_factory=dict)


class DiagnosticLogsResponse(BaseModel):
    retention_days: int
    log_dir: str
    items: list[DiagnosticLogEventResponse]
