from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, asc, desc, select
from sqlalchemy.orm import Session, joinedload

from encodr_core.execution import ExecutionResult
from encodr_db.models import (
    FileLifecycleState,
    Job,
    JobStatus,
    PlanSnapshot,
    ReplacementStatus,
    TrackedFile,
    VerificationStatus,
)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job_from_plan(
        self,
        tracked_file: TrackedFile,
        plan_snapshot: PlanSnapshot,
        *,
        worker_name: str | None = None,
        attempt_count: int = 1,
    ) -> Job:
        payload = plan_snapshot.payload
        replace_payload = payload["replace"]
        job = Job(
            tracked_file_id=tracked_file.id,
            plan_snapshot_id=plan_snapshot.id,
            worker_name=worker_name,
            status=JobStatus.PENDING,
            attempt_count=attempt_count,
            verification_status=VerificationStatus.PENDING,
            replacement_status=ReplacementStatus.PENDING,
            replace_in_place=replace_payload["in_place"],
            require_verification=replace_payload["require_verification"],
            keep_original_until_verified=replace_payload["keep_original_until_verified"],
            delete_replaced_source=replace_payload["delete_replaced_source"],
        )
        self.session.add(job)
        tracked_file.lifecycle_state = FileLifecycleState.QUEUED
        self.session.flush()
        return job

    def fetch_next_pending_job(self) -> Job | None:
        query = (
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
            .order_by(asc(Job.created_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def get_by_id(self, job_id: str) -> Job | None:
        query = (
            select(Job)
            .where(Job.id == job_id)
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
        )
        return self.session.scalar(query)

    def mark_running(self, job: Job, *, worker_name: str) -> Job:
        job.status = JobStatus.RUNNING
        job.worker_name = worker_name
        job.started_at = datetime.now(timezone.utc)
        if job.tracked_file is not None:
            job.tracked_file.lifecycle_state = job.tracked_file.lifecycle_state.PROCESSING
        self.session.flush()
        return job

    def mark_result(self, job: Job, result: ExecutionResult) -> Job:
        status_map = {
            "completed": JobStatus.COMPLETED,
            "failed": JobStatus.FAILED,
            "skipped": JobStatus.SKIPPED,
            "manual_review": JobStatus.MANUAL_REVIEW,
        }
        job.status = status_map[result.status]
        job.completed_at = result.completed_at
        job.failure_message = result.failure_message
        job.output_path = str(result.output_path) if result.output_path is not None else None
        job.final_output_path = (
            str(result.final_output_path) if result.final_output_path is not None else None
        )
        job.original_backup_path = (
            str(result.original_backup_path) if result.original_backup_path is not None else None
        )
        job.execution_command = result.command
        job.execution_stdout = truncate_log(result.stdout)
        job.execution_stderr = truncate_log(result.stderr)
        job.verification_status = verification_status_for_result(result)
        job.verification_payload = (
            result.verification.model_dump(mode="json") if result.verification is not None else None
        )
        job.replacement_status = replacement_status_for_result(result)
        job.replacement_payload = (
            result.replacement.model_dump(mode="json") if result.replacement is not None else None
        )
        job.replacement_failure_message = (
            result.replacement.failure_message if result.replacement is not None else None
        )
        self.session.flush()
        return job

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Job]:
        query: Select[tuple[Job]] = select(Job).order_by(desc(Job.created_at))
        if status is not None:
            query = query.where(Job.status == status)
        if tracked_file_id is not None:
            query = query.where(Job.tracked_file_id == tracked_file_id)
        if worker_name is not None:
            query = query.where(Job.worker_name == worker_name)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))


def truncate_log(value: str | None, limit: int = 8000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit]


def verification_status_for_result(result: ExecutionResult) -> VerificationStatus:
    if result.verification is None:
        return VerificationStatus.NOT_REQUIRED
    if result.verification.status == "passed":
        return VerificationStatus.PASSED
    if result.verification.status == "failed":
        return VerificationStatus.FAILED
    return VerificationStatus.NOT_REQUIRED


def replacement_status_for_result(result: ExecutionResult) -> ReplacementStatus:
    if result.replacement is None:
        return ReplacementStatus.NOT_REQUIRED
    if result.replacement.status == "succeeded":
        return ReplacementStatus.SUCCEEDED
    if result.replacement.status == "failed":
        return ReplacementStatus.FAILED
    return ReplacementStatus.NOT_REQUIRED
