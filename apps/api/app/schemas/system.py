from __future__ import annotations

from pydantic import BaseModel

from app.schemas.worker import HealthStatus, QueueHealthSummaryResponse


class PathStatusResponse(BaseModel):
    role: str
    path: str
    status: HealthStatus
    message: str
    exists: bool
    is_directory: bool
    readable: bool
    writable: bool
    total_space_bytes: int | None = None
    free_space_bytes: int | None = None
    free_space_ratio: float | None = None


class StorageStatusResponse(BaseModel):
    status: HealthStatus
    summary: str
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
    scratch_dir: str
    data_dir: str
    media_mounts: list[str]
    local_worker_enabled: bool
    user_count: int | None = None
    config_sources: dict[str, str]
    warnings: list[str]
    queue_health: QueueHealthSummaryResponse
