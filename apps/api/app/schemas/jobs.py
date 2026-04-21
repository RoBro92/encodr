from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from encodr_db.models import Job


class CreateJobRequest(BaseModel):
    tracked_file_id: str | None = None
    plan_snapshot_id: str | None = None

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


class JobSummaryResponse(BaseModel):
    id: str
    tracked_file_id: str
    plan_snapshot_id: str
    source_path: str | None = None
    source_filename: str | None = None
    worker_name: str | None = None
    status: str
    attempt_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_stage: str | None = None
    progress_percent: int | None = None
    progress_out_time_seconds: int | None = None
    progress_fps: float | None = None
    progress_speed: float | None = None
    progress_updated_at: datetime | None = None
    failure_message: str | None = None
    failure_category: str | None = None
    input_size_bytes: int | None = None
    output_size_bytes: int | None = None
    space_saved_bytes: int | None = None
    video_input_size_bytes: int | None = None
    video_output_size_bytes: int | None = None
    video_space_saved_bytes: int | None = None
    non_video_space_saved_bytes: int | None = None
    compression_reduction_percent: int | None = None
    verification_status: str
    replacement_status: str
    tracked_file_is_protected: bool | None = None
    requires_review: bool = False
    review_status: str | None = None
    assigned_worker_id: str | None = None
    last_worker_id: str | None = None
    requested_worker_type: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> "JobSummaryResponse":
        return cls(
            id=job.id,
            tracked_file_id=job.tracked_file_id,
            plan_snapshot_id=job.plan_snapshot_id,
            source_path=job.tracked_file.source_path if job.tracked_file is not None else None,
            source_filename=job.tracked_file.source_filename if job.tracked_file is not None else None,
            worker_name=job.worker_name,
            status=job.status.value,
            attempt_count=job.attempt_count,
            started_at=job.started_at,
            completed_at=job.completed_at,
            progress_stage=job.progress_stage,
            progress_percent=job.progress_percent,
            progress_out_time_seconds=job.progress_out_time_seconds,
            progress_fps=job.progress_fps,
            progress_speed=job.progress_speed,
            progress_updated_at=job.progress_updated_at,
            failure_message=job.failure_message,
            failure_category=job.failure_category,
            input_size_bytes=job.input_size_bytes,
            output_size_bytes=job.output_size_bytes,
            space_saved_bytes=job.space_saved_bytes,
            video_input_size_bytes=job.video_input_size_bytes,
            video_output_size_bytes=job.video_output_size_bytes,
            video_space_saved_bytes=job.video_space_saved_bytes,
            non_video_space_saved_bytes=job.non_video_space_saved_bytes,
            compression_reduction_percent=job.compression_reduction_percent,
            verification_status=job.verification_status.value,
            replacement_status=job.replacement_status.value,
            tracked_file_is_protected=job.tracked_file.is_protected if job.tracked_file is not None else None,
            requires_review=job.status.value == "manual_review",
            review_status="open" if job.status.value == "manual_review" else None,
            assigned_worker_id=job.assigned_worker_id,
            last_worker_id=job.last_worker_id,
            requested_worker_type=job.requested_worker_type.value if job.requested_worker_type is not None else None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class JobDetailResponse(JobSummaryResponse):
    output_path: str | None = None
    final_output_path: str | None = None
    original_backup_path: str | None = None
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
            original_backup_path=job.original_backup_path,
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


BatchJobItemResponse.model_rebuild()
