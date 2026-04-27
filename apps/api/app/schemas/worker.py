from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.schedules import ScheduleWindowRequest, ScheduleWindowResponse


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


class DevicePathStatusResponse(BaseModel):
    path: str
    exists: bool
    readable: bool
    writable: bool
    is_character_device: bool
    status: str
    message: str
    vendor_id: str | None = None
    vendor_name: str | None = None


class ExecutionBackendStatusResponse(BaseModel):
    backend: str
    preference_key: str
    detected: bool
    usable_by_ffmpeg: bool
    ffmpeg_path_verified: bool
    status: str
    message: str
    reason_unavailable: str | None = None
    recommended_usage: str | None = None
    device_paths: list[DevicePathStatusResponse] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionPreferenceResponse(BaseModel):
    preferred_backend: str
    allow_cpu_fallback: bool


class PathMappingRequest(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    server_path: str = Field(min_length=1)
    worker_path: str = Field(min_length=1)

    @field_validator("label", "server_path", "worker_path", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class PathMappingResponse(BaseModel):
    label: str | None = None
    server_path: str
    worker_path: str
    marker_relative_path: str | None = None
    validation_status: str | None = None
    validation_message: str | None = None
    validated_at: datetime | None = None
    marker_server_path: str | None = None
    marker_worker_path: str | None = None


class WorkerPreferenceRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    preferred_backend: Literal[
        "cpu_only",
        "prefer_intel_igpu",
        "prefer_nvidia_gpu",
        "prefer_amd_gpu",
    ]
    allow_cpu_fallback: bool = True
    max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    schedule_windows: list[ScheduleWindowRequest] = Field(default_factory=list)
    scratch_path: str | None = None
    path_mappings: list[PathMappingRequest] = Field(default_factory=list)

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_optional_display_name(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


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
    recommended_concurrency: int | None = None
    recommended_concurrency_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    hardware_probes: list[dict[str, Any]] = Field(default_factory=list)
    capability_source: str | None = None
    capability_checked_at: datetime | None = None


class WorkerHostSummaryResponse(BaseModel):
    hostname: str | None = None
    platform: str | None = None
    agent_version: str | None = None
    python_version: str | None = None


class WorkerRuntimeSummaryResponse(BaseModel):
    queue: str | None = None
    scratch_dir: str | None = None
    scratch_status: dict[str, Any] | None = None
    media_mounts: list[str] = Field(default_factory=list)
    path_mappings: list[PathMappingResponse] = Field(default_factory=list)
    preferred_backend: str | None = None
    allow_cpu_fallback: bool | None = None
    max_concurrent_jobs: int | None = None
    current_job_id: str | None = None
    current_backend: str | None = None
    current_stage: str | None = None
    current_progress_percent: int | None = None
    current_progress_updated_at: datetime | None = None
    telemetry: dict[str, Any] | None = None
    last_completed_job_id: str | None = None
    schedule_windows: list[ScheduleWindowResponse] = Field(default_factory=list)


class WorkerBinarySummaryResponse(BaseModel):
    name: str
    configured_path: str | None = None
    resolved_path: str | None = None
    exists: bool | None = None
    executable: bool | None = None
    discoverable: bool | None = None
    status: str | None = None
    message: str | None = None
    which: dict[str, Any] | None = None


class WorkerRecentJobResponse(BaseModel):
    job_id: str
    source_filename: str | None = None
    status: str
    actual_execution_backend: str | None = None
    requested_execution_backend: str | None = None
    backend_fallback_used: bool = False
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    failure_message: str | None = None


class WorkerStatusResponse(BaseModel):
    worker_id: str | None = None
    status: HealthStatus
    summary: str
    worker_name: str
    configured: bool
    configuration_state: str
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
    hardware_probes: list[ExecutionBackendStatusResponse] = Field(default_factory=list)
    runtime_device_paths: list[DevicePathStatusResponse] = Field(default_factory=list)
    execution_preferences: ExecutionPreferenceResponse
    scratch_path: dict[str, Any] = Field(default_factory=dict)
    media_paths: list[dict[str, Any]] = Field(default_factory=list)
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_processed_job_id: str | None = None
    last_result_status: str | None = None
    last_failure_message: str | None = None
    processed_jobs: int = 0
    current_job_id: str | None = None
    current_backend: str | None = None
    current_stage: str | None = None
    current_progress_percent: int | None = None
    current_progress_updated_at: datetime | None = None
    telemetry: dict[str, Any] | None = None
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
    worker_state: str
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
    preferred_backend: str | None = None
    allow_cpu_fallback: bool | None = None
    max_concurrent_jobs: int | None = None
    scratch_path: str | None = None
    path_mappings: list[PathMappingResponse] = Field(default_factory=list)
    schedule_windows: list[ScheduleWindowResponse] = Field(default_factory=list)
    schedule_summary: str | None = None
    current_job_id: str | None = None
    current_backend: str | None = None
    current_stage: str | None = None
    current_progress_percent: int | None = None
    onboarding_platform: str | None = None
    pairing_expires_at: datetime | None = None
    pending_assignment_count: int = 0
    last_completed_job_id: str | None = None


class WorkerInventoryDetailResponse(WorkerInventorySummaryResponse):
    runtime_summary: WorkerRuntimeSummaryResponse | None = None
    binary_summary: list[WorkerBinarySummaryResponse] = Field(default_factory=list)
    assigned_job_ids: list[str] = Field(default_factory=list)
    last_processed_job_id: str | None = None
    recent_failure_message: str | None = None
    recent_jobs: list[WorkerRecentJobResponse] = Field(default_factory=list)


class WorkerInventoryListResponse(BaseModel):
    items: list[WorkerInventorySummaryResponse]


class WorkerRegistrationRequest(BaseModel):
    registration_secret: str | None = Field(default=None, min_length=1, max_length=512)
    pairing_token: str | None = Field(default=None, min_length=1, max_length=512)
    worker_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    worker_type: Literal["remote"]
    capability_summary: WorkerCapabilitySummaryResponse
    host_summary: WorkerHostSummaryResponse = Field(default_factory=WorkerHostSummaryResponse)
    runtime_summary: WorkerRuntimeSummaryResponse | None = None
    binary_summary: list[WorkerBinarySummaryResponse] = Field(default_factory=list)
    health_status: HealthStatus = HealthStatus.UNKNOWN
    health_summary: str | None = Field(default=None, max_length=2000)

    @field_validator("registration_secret", "pairing_token", mode="before")
    @classmethod
    def strip_optional_secrets(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("worker_key", "display_name", mode="before")
    @classmethod
    def strip_mandatory_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("Field must not be empty.")
            return cleaned
        return value

    @model_validator(mode="after")
    def ensure_one_registration_method(self) -> "WorkerRegistrationRequest":
        if not self.registration_secret and not self.pairing_token:
            raise ValueError("Either a registration secret or pairing token is required.")
        return self


class WorkerRegistrationResponse(BaseModel):
    worker_id: str
    worker_key: str
    display_name: str
    worker_type: str
    worker_token: str
    registration_status: str
    enabled: bool
    execution_preferences: ExecutionPreferenceResponse
    runtime_configuration: WorkerRuntimeSummaryResponse | None = None
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
    execution_preferences: ExecutionPreferenceResponse
    runtime_configuration: WorkerRuntimeSummaryResponse | None = None
    health_status: HealthStatus
    health_summary: str | None = None
    heartbeat_at: datetime


class WorkerStateChangeResponse(BaseModel):
    worker: WorkerInventoryDetailResponse
    status: str


class LocalWorkerSetupRequest(WorkerPreferenceRequest):
    enabled: bool = True


class RemoteWorkerOnboardingRequest(WorkerPreferenceRequest):
    platform: Literal["windows", "linux", "macos"]


class RemoteWorkerOnboardingResponse(BaseModel):
    worker: WorkerInventoryDetailResponse
    status: Literal["pending_pairing"]
    pairing_token_expires_at: datetime
    bootstrap_command: str
    uninstall_command: str
    notes: list[str] = Field(default_factory=list)


class WorkerRemovalResponse(BaseModel):
    worker_id: str
    worker_key: str
    status: Literal["removed"]
    uninstall_command: str
    notes: list[str] = Field(default_factory=list)


class WorkerAssignedJobResponse(BaseModel):
    job_id: str
    tracked_file_id: str
    plan_snapshot_id: str
    job_kind: str = "execution"
    source_path: str
    plan_payload: dict[str, Any]
    media_payload: dict[str, Any]
    analysis_payload: dict[str, Any] | None = None
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


class WorkerJobProgressRequest(BaseModel):
    stage: str
    percent: float | None = None
    out_time_seconds: float | None = None
    fps: float | None = None
    speed: float | None = None
    runtime_summary: WorkerRuntimeSummaryResponse | None = None


class WorkerJobProgressResponse(BaseModel):
    job_id: str
    updated_at: datetime


class WorkerJobFailureRequest(BaseModel):
    failure_message: str = Field(min_length=1, max_length=4000)
    failure_category: str = Field(min_length=1, max_length=255)
    runtime_summary: WorkerRuntimeSummaryResponse | None = None


class WorkerJobFailureResponse(BaseModel):
    job_id: str
    final_status: str
    completed_at: datetime | None = None


class WorkerJobResultRequest(BaseModel):
    result_payload: dict[str, Any]
    runtime_summary: WorkerRuntimeSummaryResponse | None = None


class WorkerJobResultResponse(BaseModel):
    job_id: str
    final_status: str
    completed_at: datetime | None = None
