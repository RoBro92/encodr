from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.schemas.schedules import ScheduleWindowRequest, ScheduleWindowResponse
from encodr_db.models import BulkQueueOperation, Job


class CreateJobRequest(BaseModel):
    tracked_file_id: str | None = None
    plan_snapshot_id: str | None = None
    preferred_worker_id: str | None = None
    pinned_worker_id: str | None = None
    preferred_backend_override: str | None = None
    schedule_windows: list[ScheduleWindowRequest] = Field(default_factory=list)
    backup_policy: str = "keep"

    @model_validator(mode="after")
    def validate_target(self) -> "CreateJobRequest":
        provided = [self.tracked_file_id is not None, self.plan_snapshot_id is not None]
        if sum(provided) != 1:
            raise ValueError("Exactly one of tracked_file_id or plan_snapshot_id must be provided.")
        return self


class CreateBatchJobsRequest(BaseModel):
    source_path: str | None = None
    folder_path: str | None = None
    selected_paths: list[str] = Field(default_factory=list)
    preferred_worker_id: str | None = None
    pinned_worker_id: str | None = None
    preferred_backend_override: str | None = None
    schedule_windows: list[ScheduleWindowRequest] = Field(default_factory=list)
    backup_policy: str = "keep"
    summary_only: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "CreateBatchJobsRequest":
        provided = sum(
            bool(value)
            for value in [
                self.source_path,
                self.folder_path,
                self.selected_paths,
            ]
        )
        if provided != 1:
            raise ValueError("Provide exactly one of source_path, folder_path, or selected_paths.")
        return self


class CreateDryRunJobsRequest(CreateBatchJobsRequest):
    ignore_worker_schedule: bool = False


class DryRunAnalysisResponse(BaseModel):
    mode: str = "dry_run"
    source_path: str
    file_name: str
    planned_action: str
    confidence: str
    requires_review: bool
    is_protected: bool
    reason_codes: list[str] = Field(default_factory=list)
    reason_messages: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    warning_messages: list[str] = Field(default_factory=list)
    selected_audio_stream_indices: list[int] = Field(default_factory=list)
    selected_subtitle_stream_indices: list[int] = Field(default_factory=list)
    audio_stream_decisions: list[dict[str, Any]] = Field(default_factory=list)
    subtitle_stream_decisions: list[dict[str, Any]] = Field(default_factory=list)
    output_filename: str
    current_size_bytes: int | None = None
    estimated_output_size_bytes: int | None = None
    estimated_space_saved_bytes: int | None = None
    audio_tracks_removed_count: int = 0
    subtitle_tracks_removed_count: int = 0
    summary: str
    video_handling: str
    source_video_bitrate_bps: int | None = None
    estimated_output_video_bitrate_bps: int | None = None
    target_crf: int | None = None
    low_bitrate_skip_threshold_bps: int | None = None
    minimum_output_bitrate_bps: int | None = None
    max_allowed_video_reduction_percent: int | None = None
    output_larger_than_input_review_percent: int | None = None
    manual_review_triggered: bool = False
    manual_review_reasons: list[str] = Field(default_factory=list)


class BatchJobItemResponse(BaseModel):
    source_path: str
    status: str
    message: str | None = None
    job: "JobDetailResponse | None" = None


class BatchJobCreateResponse(BaseModel):
    scope: str
    total_files: int
    created_count: int
    blocked_count: int
    items: list[BatchJobItemResponse]


class DryRunJobCreateResponse(BaseModel):
    mode: str = "dry_run"
    scope: str
    total_files: int
    created_count: int
    blocked_count: int
    warning_threshold: int = 15
    items: list[BatchJobItemResponse]


class BulkQueueStartRequest(CreateBatchJobsRequest):
    pass


class BulkQueueOperationItemResponse(BaseModel):
    source_path: str
    status: str
    message: str | None = None


class BulkQueueOperationResponse(BaseModel):
    id: str
    scope: str
    status: str
    stage: str
    status_text: str | None = None
    batch_size: int
    total_expected: int
    discovered_count: int
    queued_count: int
    skipped_count: int
    blocked_count: int
    failed_count: int
    current_batch: int
    total_batches: int
    error_summary: str | None = None
    items: list[BulkQueueOperationItemResponse] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, operation: BulkQueueOperation) -> "BulkQueueOperationResponse":
        result_summary = operation.result_summary if isinstance(operation.result_summary, dict) else {}
        raw_items = result_summary.get("items") if isinstance(result_summary, dict) else []
        items = raw_items if isinstance(raw_items, list) else []
        return cls(
            id=operation.id,
            scope=operation.scope,
            status=operation.status,
            stage=operation.stage,
            status_text=operation.status_text,
            batch_size=operation.batch_size,
            total_expected=operation.total_expected,
            discovered_count=operation.discovered_count,
            queued_count=operation.queued_count,
            skipped_count=operation.skipped_count,
            blocked_count=operation.blocked_count,
            failed_count=operation.failed_count,
            current_batch=operation.current_batch,
            total_batches=operation.total_batches,
            error_summary=operation.error_summary,
            items=[
                BulkQueueOperationItemResponse(
                    source_path=str(item.get("source_path", "")),
                    status=str(item.get("status", "")),
                    message=str(item.get("message")) if item.get("message") else None,
                )
                for item in items
                if isinstance(item, dict)
            ],
            started_at=operation.started_at,
            completed_at=operation.completed_at,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
        )


class BulkQueueOperationListResponse(BaseModel):
    items: list[BulkQueueOperationResponse]


class BulkJobActionResponse(BaseModel):
    status: str
    affected_count: int
    affected_job_ids: list[str] = Field(default_factory=list)


class BulkJobClearRequest(BaseModel):
    job_ids: list[str] | None = None


class BulkJobResolveRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1)
    action: Literal["retry", "skip"]


class RetryJobRequest(BaseModel):
    existing_backup_strategy: Literal["fail", "replace_backup", "keep_existing_backup"] = "fail"


class JobBackupResponse(BaseModel):
    job_id: str
    tracked_file_id: str
    source_path: str | None = None
    source_filename: str | None = None
    backup_path: str
    backup_policy: str
    created_at: datetime | None = None
    retention_until: datetime | None = None
    deleted_at: datetime | None = None
    restored_at: datetime | None = None

    @classmethod
    def from_model(cls, job: Job) -> "JobBackupResponse":
        return cls(
            job_id=job.id,
            tracked_file_id=job.tracked_file_id,
            source_path=job.tracked_file.source_path if job.tracked_file is not None else None,
            source_filename=job.tracked_file.source_filename if job.tracked_file is not None else None,
            backup_path=job.original_backup_path or "",
            backup_policy=job.backup_policy,
            created_at=job.completed_at,
            retention_until=job.backup_retention_until,
            deleted_at=job.backup_deleted_at,
            restored_at=job.backup_restored_at,
        )


class JobBackupListResponse(BaseModel):
    items: list[JobBackupResponse]
    limit: int | None = None
    offset: int = 0
    total: int = 0


class JobSummaryResponse(BaseModel):
    id: str
    tracked_file_id: str
    plan_snapshot_id: str
    job_kind: str
    source_path: str | None = None
    source_filename: str | None = None
    worker_name: str | None = None
    status: str
    attempt_count: int
    duration_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_stage: str | None = None
    progress_percent: int | None = None
    progress_out_time_seconds: int | None = None
    progress_fps: float | None = None
    progress_speed: float | None = None
    progress_updated_at: datetime | None = None
    requested_execution_backend: str | None = None
    actual_execution_backend: str | None = None
    actual_execution_accelerator: str | None = None
    backend_fallback_used: bool = False
    backend_selection_reason: str | None = None
    failure_message: str | None = None
    failure_category: str | None = None
    failure_code: str | None = None
    skipped_reason: str | None = None
    input_size_bytes: int | None = None
    output_size_bytes: int | None = None
    space_saved_bytes: int | None = None
    video_input_size_bytes: int | None = None
    video_output_size_bytes: int | None = None
    video_space_saved_bytes: int | None = None
    non_video_space_saved_bytes: int | None = None
    compression_reduction_percent: int | None = None
    output_growth_percent: float | None = None
    output_growth_guard_percent: int | None = None
    audio_tracks_removed_count: int = 0
    subtitle_tracks_removed_count: int = 0
    plan_reason_codes: list[str] = Field(default_factory=list)
    plan_reason_messages: list[str] = Field(default_factory=list)
    analysis_payload: DryRunAnalysisResponse | None = None
    verification_status: str
    replacement_status: str
    tracked_file_is_protected: bool | None = None
    requires_review: bool = False
    review_status: str | None = None
    assigned_worker_id: str | None = None
    last_worker_id: str | None = None
    preferred_worker_id: str | None = None
    pinned_worker_id: str | None = None
    preferred_backend_override: str | None = None
    schedule_windows: list[ScheduleWindowResponse] = Field(default_factory=list)
    schedule_summary: str | None = None
    scheduled_for_at: datetime | None = None
    interrupted_at: datetime | None = None
    interruption_reason: str | None = None
    interruption_retryable: bool = True
    cleared_at: datetime | None = None
    cleared_reason: str | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_reason: str | None = None
    backup_policy: str
    original_backup_path: str | None = None
    backup_retention_until: datetime | None = None
    backup_deleted_at: datetime | None = None
    backup_restored_at: datetime | None = None
    watched_job_id: str | None = None
    requested_worker_type: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> "JobSummaryResponse":
        analysis_payload = job_dry_run_analysis_payload(job)
        return cls(
            id=job.id,
            tracked_file_id=job.tracked_file_id,
            plan_snapshot_id=job.plan_snapshot_id,
            job_kind=job.job_kind.value,
            source_path=job.tracked_file.source_path if job.tracked_file is not None else None,
            source_filename=job.tracked_file.source_filename if job.tracked_file is not None else None,
            worker_name=job.worker_name,
            status=job.status.value,
            attempt_count=job.attempt_count,
            duration_seconds=job_duration_seconds(job),
            started_at=job.started_at,
            completed_at=job.completed_at,
            progress_stage=job.progress_stage,
            progress_percent=job.progress_percent,
            progress_out_time_seconds=job.progress_out_time_seconds,
            progress_fps=job.progress_fps,
            progress_speed=job.progress_speed,
            progress_updated_at=job.progress_updated_at,
            requested_execution_backend=job.requested_execution_backend,
            actual_execution_backend=job.actual_execution_backend,
            actual_execution_accelerator=job.actual_execution_accelerator,
            backend_fallback_used=job.backend_fallback_used,
            backend_selection_reason=job.backend_selection_reason,
            failure_message=job.failure_message,
            failure_category=job.failure_category,
            failure_code=job_failure_code(job),
            skipped_reason=job_skipped_reason(job),
            input_size_bytes=job.input_size_bytes,
            output_size_bytes=job.output_size_bytes if job.output_size_bytes is not None else (
                analysis_payload.estimated_output_size_bytes if analysis_payload is not None else None
            ),
            space_saved_bytes=job.space_saved_bytes if job.space_saved_bytes is not None else (
                analysis_payload.estimated_space_saved_bytes if analysis_payload is not None else None
            ),
            video_input_size_bytes=job.video_input_size_bytes,
            video_output_size_bytes=job.video_output_size_bytes,
            video_space_saved_bytes=job.video_space_saved_bytes,
            non_video_space_saved_bytes=job.non_video_space_saved_bytes,
            compression_reduction_percent=job.compression_reduction_percent,
            output_growth_percent=job_output_growth_percent(job),
            output_growth_guard_percent=job_output_growth_guard_percent(job),
            audio_tracks_removed_count=job_removed_audio_tracks(job),
            subtitle_tracks_removed_count=job_removed_subtitle_tracks(job),
            plan_reason_codes=job_plan_reason_codes(job),
            plan_reason_messages=job_plan_reason_messages(job),
            analysis_payload=analysis_payload,
            verification_status=job.verification_status.value,
            replacement_status=job.replacement_status.value,
            tracked_file_is_protected=job.tracked_file.is_protected if job.tracked_file is not None else None,
            requires_review=job.status.value == "manual_review" or dry_run_requires_review(job),
            review_status="open" if job.status.value == "manual_review" else ("would_review" if dry_run_requires_review(job) else None),
            assigned_worker_id=job.assigned_worker_id,
            last_worker_id=job.last_worker_id,
            preferred_worker_id=job.preferred_worker_id,
            pinned_worker_id=job.pinned_worker_id,
            preferred_backend_override=job.preferred_backend_override,
            schedule_windows=[
                ScheduleWindowResponse(**item)
                for item in (job.schedule_windows or [])
            ],
            schedule_summary=job.schedule_summary,
            scheduled_for_at=job.scheduled_for_at,
            interrupted_at=job.interrupted_at,
            interruption_reason=job.interruption_reason,
            interruption_retryable=job.interruption_retryable,
            cleared_at=job.cleared_at,
            cleared_reason=job.cleared_reason,
            cancellation_requested_at=job.cancellation_requested_at,
            cancellation_reason=job.cancellation_reason,
            backup_policy=job.backup_policy,
            original_backup_path=job.original_backup_path,
            backup_retention_until=job.backup_retention_until,
            backup_deleted_at=job.backup_deleted_at,
            backup_restored_at=job.backup_restored_at,
            watched_job_id=job.watched_job_id,
            requested_worker_type=job.requested_worker_type.value if job.requested_worker_type is not None else None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class JobDetailResponse(JobSummaryResponse):
    output_path: str | None = None
    final_output_path: str | None = None
    execution_command: list[str] | None = None
    execution_stdout: str | None = None
    execution_stderr: str | None = None
    verification_payload: dict[str, Any] | None = None
    replacement_payload: dict[str, Any] | None = None
    replacement_failure_message: str | None = None
    replace_in_place: bool
    require_verification: bool
    keep_original_until_verified: bool
    delete_replaced_source: bool

    @classmethod
    def from_model(cls, job: Job) -> "JobDetailResponse":
        summary = JobSummaryResponse.from_model(job)
        return cls(
            **summary.model_dump(),
            output_path=job.output_path,
            final_output_path=job.final_output_path,
            execution_command=job.execution_command,
            execution_stdout=job.execution_stdout,
            execution_stderr=job.execution_stderr,
            verification_payload=job.verification_payload,
            replacement_payload=job.replacement_payload,
            replacement_failure_message=job.replacement_failure_message,
            replace_in_place=job.replace_in_place,
            require_verification=job.require_verification,
            keep_original_until_verified=job.keep_original_until_verified,
            delete_replaced_source=job.delete_replaced_source,
        )


class JobListResponse(BaseModel):
    items: list[JobSummaryResponse]
    limit: int | None = None
    offset: int = 0
    total: int = 0


BatchJobItemResponse.model_rebuild()


def job_duration_seconds(job: Job) -> int | None:
    if job.started_at is None or job.completed_at is None:
        return None
    duration = (job.completed_at - job.started_at).total_seconds()
    if duration < 0:
        return None
    return int(round(duration))


def job_failure_code(job: Job) -> str | None:
    replacement_payload = job.replacement_payload if isinstance(job.replacement_payload, dict) else {}
    details = replacement_payload.get("details")
    if isinstance(details, dict) and details.get("failure_code"):
        return str(details["failure_code"])
    message = " ".join(
        value
        for value in [
            job.failure_message,
            job.replacement_failure_message,
        ]
        if value
    ).lower()
    if "backup file already exists" in message:
        return "backup_already_exists"
    return job.failure_category


def job_removed_audio_tracks(job: Job) -> int:
    if isinstance(job.analysis_payload, dict) and "audio_tracks_removed_count" in job.analysis_payload:
        return int(job.analysis_payload.get("audio_tracks_removed_count") or 0)
    payload = getattr(job.plan_snapshot, "payload", None)
    if not isinstance(payload, dict):
        return 0
    audio = payload.get("audio")
    if not isinstance(audio, dict):
        return 0
    dropped = audio.get("dropped_stream_indices")
    if not isinstance(dropped, list):
        return 0
    return len(dropped)


def job_removed_subtitle_tracks(job: Job) -> int:
    if isinstance(job.analysis_payload, dict) and "subtitle_tracks_removed_count" in job.analysis_payload:
        return int(job.analysis_payload.get("subtitle_tracks_removed_count") or 0)
    payload = getattr(job.plan_snapshot, "payload", None)
    if not isinstance(payload, dict):
        return 0
    subtitles = payload.get("subtitles")
    if not isinstance(subtitles, dict):
        return 0
    dropped = subtitles.get("dropped_stream_indices")
    if not isinstance(dropped, list):
        return 0
    return len(dropped)


def job_plan_reason_codes(job: Job) -> list[str]:
    return [
        str(reason.get("code"))
        for reason in _job_plan_reasons(job)
        if reason.get("code")
    ]


def job_plan_reason_messages(job: Job) -> list[str]:
    return [
        str(reason.get("message"))
        for reason in _job_plan_reasons(job)
        if reason.get("message")
    ]


def _job_plan_reasons(job: Job) -> list[dict]:
    payload = getattr(job.plan_snapshot, "payload", None)
    if not isinstance(payload, dict):
        return []
    reasons = payload.get("reasons")
    if not isinstance(reasons, list):
        return []
    return [reason for reason in reasons if isinstance(reason, dict)]


def job_skipped_reason(job: Job) -> str | None:
    if job.status.value != "skipped":
        return None
    if job.failure_message:
        return job.failure_message

    payload = getattr(job.plan_snapshot, "payload", None)
    if isinstance(payload, dict):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            is_already_compliant = summary.get("is_already_compliant")
            if is_already_compliant is True:
                return "Already efficient under the active processing policy."
        action = payload.get("action")
        if action == "skip":
            reasons = payload.get("reasons")
            if isinstance(reasons, list):
                for reason in reasons:
                    if not isinstance(reason, dict):
                        continue
                    message = reason.get("message")
                    if isinstance(message, str) and message.strip():
                        return message.strip()
                    code = reason.get("code")
                    if isinstance(code, str) and code.strip():
                        return code.replace("_", " ")

    reasons = getattr(job.plan_snapshot, "reasons", None)
    if isinstance(reasons, list):
        for reason in reasons:
            if not isinstance(reason, dict):
                continue
            message = reason.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            code = reason.get("code")
            if isinstance(code, str) and code.strip():
                return code.replace("_", " ")

    return "Skipped because no replacement work was required."


def dry_run_requires_review(job: Job) -> bool:
    payload = job_dry_run_analysis_payload(job)
    return bool(payload.requires_review) if payload is not None else False


def job_output_growth_percent(job: Job) -> float | None:
    if job.input_size_bytes is None or job.output_size_bytes is None or job.input_size_bytes <= 0:
        return None
    return round(((job.output_size_bytes - job.input_size_bytes) / job.input_size_bytes) * 100.0, 1)


def job_output_growth_guard_percent(job: Job) -> int | None:
    plan_payload = getattr(getattr(job, "plan_snapshot", None), "payload", None)
    if not isinstance(plan_payload, dict):
        return None
    video_payload = plan_payload.get("video")
    if not isinstance(video_payload, dict):
        return None
    value = video_payload.get("output_larger_than_input_review_percent")
    return int(value) if isinstance(value, int) else None


def job_dry_run_analysis_payload(job: Job) -> DryRunAnalysisResponse | None:
    payload = getattr(job, "analysis_payload", None)
    if not isinstance(payload, dict):
        return None
    try:
        return DryRunAnalysisResponse.model_validate(payload)
    except ValidationError:
        return None
