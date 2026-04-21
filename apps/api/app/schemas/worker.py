from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class BinaryStatusResponse(BaseModel):
    configured_path: str
    resolved_path: str | None = None
    discoverable: bool
    exists: bool
    executable: bool
    status: HealthStatus
    message: str


class QueueHealthSummaryResponse(BaseModel):
    status: HealthStatus
    summary: str
    pending_count: int
    running_count: int
    failed_count: int
    manual_review_count: int
    completed_count: int
    oldest_pending_age_seconds: int | None = None
    last_completed_age_seconds: int | None = None
    recent_failed_count: int = 0
    recent_manual_review_count: int = 0


class WorkerRunOnceResponse(BaseModel):
    processed_job: bool
    job_id: str | None = None
    final_status: str | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkerCapabilitySummaryResponse(BaseModel):
    execution_modes: list[str] = Field(default_factory=list)
    supported_video_codecs: list[str] = Field(default_factory=list)
    supported_audio_codecs: list[str] = Field(default_factory=list)
    hardware_hints: list[str] = Field(default_factory=list)
    binary_support: dict[str, bool] = Field(default_factory=dict)
    max_concurrent_jobs: int | None = None
    tags: list[str] = Field(default_factory=list)


class WorkerHostSummaryResponse(BaseModel):
    hostname: str | None = None
    platform: str | None = None
    agent_version: str | None = None
    python_version: str | None = None


class WorkerRuntimeSummaryResponse(BaseModel):
    queue: str | None = None
    scratch_dir: str | None = None
    media_mounts: list[str] = Field(default_factory=list)
    last_completed_job_id: str | None = None


class WorkerBinarySummaryResponse(BaseModel):
    name: str
    configured_path: str | None = None
    discoverable: bool | None = None
    message: str | None = None


class WorkerStatusResponse(BaseModel):
    status: HealthStatus
    summary: str
    worker_name: str
    mode: str
    local_only: bool
    enabled: bool
    available: bool
    eligible: bool
    eligibility_summary: str
    default_queue: str
    ffmpeg: BinaryStatusResponse
    ffprobe: BinaryStatusResponse
    local_worker_queue: str
    execution_backends: list[str] = Field(default_factory=list)
    hardware_acceleration: list[str] = Field(default_factory=list)
    hardware_probes: list[dict[str, Any]] = Field(default_factory=list)
    scratch_path: dict[str, Any] = Field(default_factory=dict)
    media_paths: list[dict[str, Any]] = Field(default_factory=list)
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_processed_job_id: str | None = None
    last_result_status: str | None = None
    last_failure_message: str | None = None
    processed_jobs: int = 0
    capabilities: dict[str, bool]
    queue_health: QueueHealthSummaryResponse
    self_test_available: bool = True


class WorkerSelfTestCheckResponse(BaseModel):
    code: str
    status: HealthStatus
    message: str


class WorkerSelfTestResponse(BaseModel):
    status: HealthStatus
    summary: str
    worker_name: str
    started_at: datetime
    completed_at: datetime
    checks: list[WorkerSelfTestCheckResponse]


class WorkerInventorySummaryResponse(BaseModel):
    id: str
    worker_key: str
    display_name: str
    worker_type: str
    source: str
    enabled: bool
    registration_status: str
    health_status: HealthStatus
    health_summary: str | None = None
    last_seen_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_registration_at: datetime | None = None
    capability_summary: WorkerCapabilitySummaryResponse
    host_summary: WorkerHostSummaryResponse
    pending_assignment_count: int = 0
    last_completed_job_id: str | None = None


class WorkerInventoryDetailResponse(WorkerInventorySummaryResponse):
    runtime_summary: WorkerRuntimeSummaryResponse | None = None
    binary_summary: list[WorkerBinarySummaryResponse] = Field(default_factory=list)
    assigned_job_ids: list[str] = Field(default_factory=list)
    last_processed_job_id: str | None = None
    recent_failure_message: str | None = None


class WorkerInventoryListResponse(BaseModel):
    items: list[WorkerInventorySummaryResponse]


class WorkerRegistrationRequest(BaseModel):
    registration_secret: str = Field(min_length=1, max_length=512)
    worker_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    worker_type: Literal["remote"]
    capability_summary: WorkerCapabilitySummaryResponse
    host_summary: WorkerHostSummaryResponse = Field(default_factory=WorkerHostSummaryResponse)
    runtime_summary: WorkerRuntimeSummaryResponse | None = None
    binary_summary: list[WorkerBinarySummaryResponse] = Field(default_factory=list)
    health_status: HealthStatus = HealthStatus.UNKNOWN
    health_summary: str | None = Field(default=None, max_length=2000)

    @field_validator("registration_secret", "worker_key", "display_name", mode="before")
    @classmethod
    def strip_required_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("Field must not be empty.")
            return cleaned
        return value


class WorkerRegistrationResponse(BaseModel):
    worker_id: str
    worker_key: str
    display_name: str
    worker_type: str
    worker_token: str
    registration_status: str
    enabled: bool
    health_status: HealthStatus
    health_summary: str | None = None
    issued_at: datetime


class WorkerHeartbeatRequest(BaseModel):
    capability_summary: WorkerCapabilitySummaryResponse | None = None
    host_summary: WorkerHostSummaryResponse | None = None
    runtime_summary: WorkerRuntimeSummaryResponse | None = None
    binary_summary: list[WorkerBinarySummaryResponse] = Field(default_factory=list)
    health_status: HealthStatus = HealthStatus.UNKNOWN
    health_summary: str | None = Field(default=None, max_length=2000)


class WorkerHeartbeatResponse(BaseModel):
    worker_id: str
    worker_key: str
    enabled: bool
    registration_status: str
    health_status: HealthStatus
    health_summary: str | None = None
    heartbeat_at: datetime


class WorkerStateChangeResponse(BaseModel):
    worker: WorkerInventoryDetailResponse
    status: str


class WorkerAssignedJobResponse(BaseModel):
    job_id: str
    tracked_file_id: str
    plan_snapshot_id: str
    source_path: str
    plan_payload: dict[str, Any]
    media_payload: dict[str, Any]
    requested_worker_type: str | None = None
    assignment_state: Literal["assigned", "claimed"] = "assigned"
    assigned_worker_id: str | None = None


class WorkerJobPollResponse(BaseModel):
    status: Literal["assigned", "no_job"]
    job: WorkerAssignedJobResponse | None = None


class WorkerJobClaimResponse(BaseModel):
    status: Literal["claimed"]
    job_id: str
    claimed_at: datetime


class WorkerJobResultRequest(BaseModel):
    result_payload: dict[str, Any]
    runtime_summary: WorkerRuntimeSummaryResponse | None = None


class WorkerJobResultResponse(BaseModel):
    job_id: str
    final_status: str
    completed_at: datetime | None = None
