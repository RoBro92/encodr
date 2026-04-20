from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator

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


class JobSummaryResponse(BaseModel):
    id: str
    tracked_file_id: str
    plan_snapshot_id: str
    worker_name: str | None = None
    status: str
    attempt_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_message: str | None = None
    verification_status: str
    replacement_status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> "JobSummaryResponse":
        return cls(
            id=job.id,
            tracked_file_id=job.tracked_file_id,
            plan_snapshot_id=job.plan_snapshot_id,
            worker_name=job.worker_name,
            status=job.status.value,
            attempt_count=job.attempt_count,
            started_at=job.started_at,
            completed_at=job.completed_at,
            failure_message=job.failure_message,
            verification_status=job.verification_status.value,
            replacement_status=job.replacement_status.value,
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
