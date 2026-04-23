from __future__ import annotations

from datetime import datetime, timezone
from math import floor

from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from encodr_core.execution import normalise_backend_preference
from encodr_core.execution import ExecutionProgressUpdate, ExecutionResult
from encodr_shared.scheduling import next_schedule_opening, schedule_windows_allow_now, schedule_windows_summary
from encodr_db.models import (
    FileLifecycleState,
    Job,
    JobKind,
    JobStatus,
    PlanSnapshot,
    ReplacementStatus,
    TrackedFile,
    VerificationStatus,
    Worker,
    WorkerType,
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
        preferred_worker_id: str | None = None,
        pinned_worker_id: str | None = None,
        preferred_backend_override: str | None = None,
        schedule_windows: list[dict] | None = None,
        watched_job_id: str | None = None,
        job_kind: JobKind = JobKind.EXECUTION,
        analysis_payload: dict | None = None,
        ignore_worker_schedule: bool = False,
    ) -> Job:
        payload = plan_snapshot.payload
        replace_payload = payload["replace"]
        scheduled_for_at = next_schedule_opening(schedule_windows)
        starts_scheduled = bool(schedule_windows and not schedule_windows_allow_now(schedule_windows))
        job = Job(
            tracked_file_id=tracked_file.id,
            plan_snapshot_id=plan_snapshot.id,
            preferred_worker_id=preferred_worker_id,
            pinned_worker_id=pinned_worker_id,
            watched_job_id=watched_job_id,
            job_kind=job_kind,
            preferred_backend_override=normalise_backend_preference(preferred_backend_override)
            if preferred_backend_override is not None
            else None,
            schedule_windows=schedule_windows,
            schedule_summary=schedule_windows_summary(schedule_windows),
            ignore_worker_schedule=ignore_worker_schedule,
            worker_name=worker_name,
            status=JobStatus.SCHEDULED if starts_scheduled else JobStatus.PENDING,
            attempt_count=attempt_count,
            requested_worker_type=None,
            input_size_bytes=tracked_file.last_observed_size,
            analysis_payload=analysis_payload,
            scheduled_for_at=scheduled_for_at if starts_scheduled else None,
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

    def fetch_next_pending_local_jobs(self, *, limit: int = 25) -> list[Job]:
        query = (
            select(Job)
            .where(
                Job.status == JobStatus.PENDING,
                Job.assigned_worker_id.is_(None),
                or_(Job.requested_worker_type.is_(None), Job.requested_worker_type == WorkerType.LOCAL),
            )
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
            .order_by(asc(Job.created_at))
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def fetch_next_pending_local_job(self) -> Job | None:
        items = self.fetch_next_pending_local_jobs(limit=1)
        return items[0] if items else None

    def fetch_next_pending_remote_jobs(self, worker: Worker, *, limit: int = 25) -> list[Job]:
        query = (
            select(Job)
            .where(
                Job.status == JobStatus.PENDING,
                or_(Job.requested_worker_type.is_(None), Job.requested_worker_type == WorkerType.REMOTE),
                or_(Job.assigned_worker_id.is_(None), Job.assigned_worker_id == worker.id),
            )
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
            .order_by(
                desc(Job.assigned_worker_id == worker.id),
                asc(Job.created_at),
            )
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def fetch_next_pending_remote_job(self, worker: Worker) -> Job | None:
        items = self.fetch_next_pending_remote_jobs(worker, limit=1)
        return items[0] if items else None

    def count_active_assignments_for_worker(self, worker_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Job.id)).where(
                    Job.assigned_worker_id == worker_id,
                    Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                )
            )
            or 0
        )

    def list_jobs_for_scheduling(self, *, limit: int = 200) -> list[Job]:
        query = (
            select(Job)
            .where(Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]))
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
            .order_by(asc(Job.created_at))
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def list_running_jobs(self, *, limit: int = 200) -> list[Job]:
        query = (
            select(Job)
            .where(Job.status == JobStatus.RUNNING)
            .options(joinedload(Job.assigned_worker), joinedload(Job.tracked_file))
            .order_by(asc(Job.started_at))
            .limit(limit)
        )
        return list(self.session.scalars(query))

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

    def get_latest_for_tracked_file(self, tracked_file_id: str) -> Job | None:
        query = (
            select(Job)
            .where(Job.tracked_file_id == tracked_file_id)
            .options(
                joinedload(Job.tracked_file),
                joinedload(Job.plan_snapshot).joinedload(PlanSnapshot.probe_snapshot),
            )
            .order_by(desc(Job.created_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def mark_running(self, job: Job, *, worker_name: str, requested_backend: str | None = None) -> Job:
        job.status = JobStatus.RUNNING
        job.worker_name = worker_name
        job.started_at = datetime.now(timezone.utc)
        job.interrupted_at = None
        job.interruption_reason = None
        job.progress_stage = "starting"
        job.progress_percent = 0
        job.progress_out_time_seconds = 0
        job.progress_fps = None
        job.progress_speed = None
        job.progress_updated_at = job.started_at
        if requested_backend is not None:
            job.requested_execution_backend = normalise_backend_preference(requested_backend)
        if job.tracked_file is not None:
            job.tracked_file.lifecycle_state = job.tracked_file.lifecycle_state.PROCESSING
        self.session.flush()
        return job

    def mark_scheduled(self, job: Job, *, scheduled_for_at: datetime | None) -> Job:
        job.status = JobStatus.SCHEDULED
        job.scheduled_for_at = scheduled_for_at
        self.session.flush()
        return job

    def promote_scheduled(self, job: Job) -> Job:
        job.status = JobStatus.PENDING
        job.scheduled_for_at = None
        self.session.flush()
        return job

    def assign_worker(self, job: Job, *, worker: Worker) -> Job:
        job.assigned_worker_id = worker.id
        job.worker_name = worker.display_name
        self.session.flush()
        return job

    def mark_running_for_worker(self, job: Job, *, worker: Worker, requested_backend: str | None = None) -> Job:
        self.mark_running(job, worker_name=worker.display_name, requested_backend=requested_backend)
        job.assigned_worker_id = worker.id
        job.last_worker_id = worker.id
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
        job.failure_category = result.failure_category
        job.requested_execution_backend = result.requested_backend
        job.actual_execution_backend = result.actual_backend
        job.actual_execution_accelerator = result.actual_accelerator
        job.backend_fallback_used = result.backend_fallback_used
        job.backend_selection_reason = result.backend_selection_reason
        job.output_size_bytes = result.output_size_bytes
        job.space_saved_bytes = calculate_space_saved(job.input_size_bytes, result.output_size_bytes)
        job.video_input_size_bytes = result.video_input_size_bytes
        job.video_output_size_bytes = result.video_output_size_bytes
        job.video_space_saved_bytes = result.video_space_saved_bytes
        job.non_video_space_saved_bytes = result.non_video_space_saved_bytes
        job.compression_reduction_percent = (
            int(round(result.compression_reduction_percent))
            if result.compression_reduction_percent is not None
            else None
        )
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
        job.analysis_payload = result.analysis_payload
        job.progress_stage = "completed" if result.status == "completed" else result.status
        job.progress_percent = 100 if result.status in {"completed", "skipped"} else job.progress_percent
        job.progress_updated_at = result.completed_at
        job.assigned_worker_id = None
        self.session.flush()
        return job

    def mark_interrupted(
        self,
        job: Job,
        *,
        interrupted_at: datetime,
        reason: str,
        retryable: bool = True,
    ) -> Job:
        job.status = JobStatus.INTERRUPTED
        job.interrupted_at = interrupted_at
        job.interruption_reason = reason
        job.interruption_retryable = retryable
        job.failure_message = reason
        job.failure_category = "worker_interrupted"
        job.progress_stage = "interrupted"
        job.progress_updated_at = interrupted_at
        job.assigned_worker_id = None
        self.session.flush()
        return job

    def record_progress(
        self,
        job: Job,
        *,
        update: ExecutionProgressUpdate,
    ) -> Job:
        job.progress_stage = update.stage
        job.progress_percent = int(floor(update.percent)) if update.percent is not None else None
        job.progress_out_time_seconds = (
            int(floor(update.out_time_seconds))
            if update.out_time_seconds is not None
            else None
        )
        job.progress_fps = update.fps
        job.progress_speed = update.speed
        job.progress_updated_at = update.updated_at
        self.session.flush()
        return job

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        job_kind: JobKind | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Job]:
        query: Select[tuple[Job]] = (
            select(Job)
            .options(joinedload(Job.tracked_file), joinedload(Job.plan_snapshot))
            .order_by(desc(Job.created_at))
        )
        if status is not None:
            query = query.where(Job.status == status)
        if job_kind is not None:
            query = query.where(Job.job_kind == job_kind)
        if tracked_file_id is not None:
            query = query.where(Job.tracked_file_id == tracked_file_id)
        if worker_name is not None:
            query = query.where(Job.worker_name == worker_name)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def has_active_job_for_tracked_file(self, tracked_file_id: str) -> bool:
        query = select(Job.id).where(
            Job.tracked_file_id == tracked_file_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING]),
        ).limit(1)
        return self.session.scalar(query) is not None

    def count_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status).order_by(Job.status.asc())
        ).all()
        return {status.value: int(count) for status, count in rows}

    def count_recent_statuses(
        self,
        statuses: list[JobStatus],
        *,
        since: datetime,
    ) -> int:
        return int(
            self.session.scalar(
                select(func.count(Job.id)).where(
                    Job.status.in_(statuses),
                    Job.updated_at >= since,
                )
            )
            or 0
        )

    def oldest_created_at_for_status(self, status: JobStatus) -> datetime | None:
        return self.session.scalar(
            select(func.min(Job.created_at)).where(Job.status == status)
        )

    def latest_completed_at(self) -> datetime | None:
        return self.session.scalar(
            select(func.max(Job.completed_at)).where(
                Job.status.in_([JobStatus.COMPLETED, JobStatus.SKIPPED])
            )
        )

    def list_recent_for_worker(
        self,
        *,
        worker_name: str | None = None,
        worker_id: str | None = None,
        limit: int = 5,
    ) -> list[Job]:
        query: Select[tuple[Job]] = (
            select(Job)
            .options(joinedload(Job.tracked_file))
            .where(
                Job.status.in_(
                    [
                        JobStatus.COMPLETED,
                        JobStatus.FAILED,
                        JobStatus.MANUAL_REVIEW,
                        JobStatus.SKIPPED,
                    ]
                )
            )
        )
        if worker_id is not None:
            query = query.where(Job.last_worker_id == worker_id)
        elif worker_name is not None:
            query = query.where(Job.worker_name == worker_name)
        else:
            return []
        query = query.order_by(desc(Job.completed_at), desc(Job.updated_at)).limit(limit)
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


def calculate_space_saved(
    input_size_bytes: int | None,
    output_size_bytes: int | None,
) -> int | None:
    if input_size_bytes is None or output_size_bytes is None:
        return None
    return input_size_bytes - output_size_bytes
