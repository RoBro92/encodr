from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import floor

from sqlalchemy import Select, and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from encodr_core.execution import normalise_backend_preference
from encodr_core.execution import ExecutionProgressUpdate, ExecutionResult
from encodr_shared.scheduling import next_schedule_opening, schedule_windows_allow_now, schedule_windows_summary
from encodr_db.models import (
    ComplianceState,
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
    MAX_AUTOMATED_RETRIES = 3
    RETRY_BACKOFF_BASE_SECONDS = 60
    RETRY_BACKOFF_MAX_SECONDS = 15 * 60

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
        scheduled_for_at: datetime | None = None,
        backup_policy: str = "keep",
    ) -> Job:
        payload = plan_snapshot.payload
        replace_payload = payload["replace"]
        effective_backup_policy = normalise_backup_policy(backup_policy)
        window_opening_at = next_schedule_opening(schedule_windows)
        backoff_due_at = _normalise_datetime(scheduled_for_at) if scheduled_for_at is not None else None
        starts_scheduled = bool(
            backoff_due_at is not None
            or (schedule_windows and not schedule_windows_allow_now(schedule_windows))
        )
        effective_scheduled_for_at = backoff_due_at or window_opening_at
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
            scheduled_for_at=effective_scheduled_for_at if starts_scheduled else None,
            verification_status=VerificationStatus.PENDING,
            replacement_status=ReplacementStatus.PENDING,
            replace_in_place=replace_payload["in_place"],
            require_verification=replace_payload["require_verification"],
            keep_original_until_verified=replace_payload["keep_original_until_verified"],
            delete_replaced_source=delete_replaced_source_for_backup_policy(
                effective_backup_policy,
                fallback=bool(replace_payload["delete_replaced_source"]),
            ),
            backup_policy=effective_backup_policy,
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
                Job.cleared_at.is_(None),
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
                Job.cleared_at.is_(None),
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
                    Job.cleared_at.is_(None),
                )
            )
            or 0
        )

    def list_jobs_for_scheduling(self, *, limit: int = 200) -> list[Job]:
        query = (
            select(Job)
            .where(
                Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]),
                Job.cleared_at.is_(None),
            )
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

    def mark_cancelling(self, job: Job, *, requested_at: datetime) -> Job:
        job.progress_stage = "cancelling"
        job.progress_updated_at = requested_at
        self.session.flush()
        return job

    def mark_cancellation_requested(
        self,
        job: Job,
        *,
        requested_at: datetime,
        reason: str,
    ) -> Job:
        job.cancellation_requested_at = requested_at
        job.cancellation_reason = reason
        job.interruption_reason = reason
        job.progress_stage = "cancellation_requested"
        job.progress_updated_at = requested_at
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
        previous_status = job.status
        status_map = {
            "completed": JobStatus.COMPLETED,
            "failed": JobStatus.FAILED,
            "skipped": JobStatus.SKIPPED,
            "manual_review": JobStatus.MANUAL_REVIEW,
            "cancelled": JobStatus.CANCELLED,
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
        if (
            result.status == "completed"
            and job.backup_policy == "keep_for_1_day"
            and job.original_backup_path
        ):
            job.backup_retention_until = result.completed_at + timedelta(days=1)
        if result.replacement is not None and result.replacement.deleted_original_source:
            job.backup_deleted_at = result.completed_at
        if result.status == "cancelled":
            job.interrupted_at = result.completed_at
            job.interruption_reason = result.failure_message
            job.interruption_retryable = True
            job.progress_stage = "cancelled"
            job.progress_percent = None
        else:
            job.progress_stage = "completed" if result.status == "completed" else result.status
        job.progress_percent = 100 if result.status in {"completed", "skipped"} else job.progress_percent
        job.progress_updated_at = result.completed_at
        job.assigned_worker_id = None
        job.scheduled_for_at = None
        self.session.flush()
        from encodr_db.repositories.telemetry import TelemetryAggregationRepository

        TelemetryAggregationRepository(self.session).record_job_result(
            job,
            previous_status=previous_status,
        )
        return job

    def apply_automatic_retry_policy(self, job: Job, result: ExecutionResult) -> Job | None:
        if result.status != "failed" or job.job_kind != JobKind.EXECUTION:
            return None

        if job_requires_manual_review(job):
            self.route_to_manual_review(
                job,
                reviewed_at=result.completed_at,
                reason=result.failure_message
                or "The failed job matches a manual-review rule and will not be retried automatically.",
                category=result.failure_category or "manual_review_required",
            )
            return None

        if job.attempt_count <= self.MAX_AUTOMATED_RETRIES:
            next_attempt_count = job.attempt_count + 1
            scheduled_for_at = result.completed_at + self.automatic_retry_delay(next_attempt_count)
            return self.create_job_from_plan(
                job.tracked_file,
                job.plan_snapshot,
                attempt_count=next_attempt_count,
                preferred_worker_id=job.preferred_worker_id,
                pinned_worker_id=job.pinned_worker_id,
                preferred_backend_override=job.preferred_backend_override,
                schedule_windows=job.schedule_windows,
                watched_job_id=job.watched_job_id,
                job_kind=job.job_kind,
                analysis_payload=job.analysis_payload,
                ignore_worker_schedule=job.ignore_worker_schedule,
                scheduled_for_at=scheduled_for_at,
                backup_policy=job.backup_policy,
            )

        self.route_to_manual_review(
            job,
            reviewed_at=result.completed_at,
            reason=(
                result.failure_message
                or "The job failed after its automated retry budget was exhausted."
            ),
            category=result.failure_category or "retry_limit_exceeded",
        )
        return None

    def automatic_retry_delay(self, attempt_count: int) -> timedelta:
        retry_index = max(0, attempt_count - 2)
        seconds = min(
            self.RETRY_BACKOFF_BASE_SECONDS * (2 ** retry_index),
            self.RETRY_BACKOFF_MAX_SECONDS,
        )
        return timedelta(seconds=seconds)

    def route_to_manual_review(
        self,
        job: Job,
        *,
        reviewed_at: datetime,
        reason: str,
        category: str,
    ) -> Job:
        job.status = JobStatus.MANUAL_REVIEW
        job.completed_at = reviewed_at
        job.failure_message = reason
        job.failure_category = category
        job.progress_stage = "manual_review"
        job.progress_updated_at = reviewed_at
        job.assigned_worker_id = None
        job.scheduled_for_at = None
        if job.tracked_file is not None:
            job.tracked_file.lifecycle_state = FileLifecycleState.MANUAL_REVIEW
            job.tracked_file.compliance_state = ComplianceState.MANUAL_REVIEW
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

    def mark_cancelled(
        self,
        job: Job,
        *,
        cancelled_at: datetime,
        reason: str = "Cancelled by operator.",
    ) -> Job:
        job.status = JobStatus.CANCELLED
        job.completed_at = cancelled_at
        job.interrupted_at = cancelled_at
        job.interruption_reason = reason
        job.interruption_retryable = True
        job.failure_message = reason
        job.failure_category = "cancelled_by_operator"
        job.progress_stage = "cancelled"
        job.progress_percent = None
        job.progress_updated_at = cancelled_at
        job.assigned_worker_id = None
        job.scheduled_for_at = None
        job.cancellation_requested_at = cancelled_at
        job.cancellation_reason = reason
        self.session.flush()
        return job

    def mark_cleared(
        self,
        job: Job,
        *,
        cleared_at: datetime,
        reason: str,
    ) -> Job:
        job.cleared_at = cleared_at
        job.cleared_reason = reason
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
        include_cleared: bool = False,
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
        if not include_cleared:
            query = query.where(Job.cleared_at.is_(None))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def has_active_job_for_tracked_file(self, tracked_file_id: str) -> bool:
        query = select(Job.id).where(
            Job.tracked_file_id == tracked_file_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.RUNNING]),
            Job.cleared_at.is_(None),
        ).limit(1)
        return self.session.scalar(query) is not None

    def count_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(Job.status, func.count(Job.id))
            .where(Job.cleared_at.is_(None))
            .group_by(Job.status)
            .order_by(Job.status.asc())
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
                    Job.cleared_at.is_(None),
                )
            )
            or 0
        )

    def oldest_created_at_for_status(self, status: JobStatus) -> datetime | None:
        return self.session.scalar(
            select(func.min(Job.created_at)).where(Job.status == status, Job.cleared_at.is_(None))
        )

    def latest_completed_at(self) -> datetime | None:
        return self.session.scalar(
            select(func.max(Job.completed_at)).where(
                Job.status.in_([JobStatus.COMPLETED, JobStatus.SKIPPED]),
                Job.cleared_at.is_(None),
            )
        )

    def clear_queue(
        self,
        *,
        cleared_at: datetime,
        reason: str = "Cleared from queue by operator.",
    ) -> list[Job]:
        query = (
            select(Job)
            .where(
                Job.cleared_at.is_(None),
                or_(
                    Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]),
                    and_(
                        Job.status == JobStatus.INTERRUPTED,
                        Job.interruption_retryable.is_(True),
                        Job.assigned_worker_id.is_(None),
                    ),
                ),
            )
            .options(joinedload(Job.tracked_file), joinedload(Job.plan_snapshot))
            .order_by(asc(Job.created_at))
        )
        jobs = list(self.session.scalars(query))
        for job in jobs:
            self.mark_cancelled(job, cancelled_at=cleared_at, reason=reason)
        return jobs

    def clear_failed_history(
        self,
        *,
        cleared_at: datetime,
        reason: str = "Cleared historical problem jobs by operator.",
    ) -> list[Job]:
        query = (
            select(Job)
            .where(
                Job.cleared_at.is_(None),
                Job.status.in_([JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.CANCELLED, JobStatus.SKIPPED]),
            )
            .options(joinedload(Job.tracked_file), joinedload(Job.plan_snapshot))
            .order_by(desc(Job.updated_at))
        )
        jobs = list(self.session.scalars(query))
        for job in jobs:
            self.mark_cleared(job, cleared_at=cleared_at, reason=reason)
        return jobs

    def list_backup_jobs(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include_missing: bool = False,
    ) -> list[Job]:
        query = (
            select(Job)
            .outerjoin(Job.tracked_file)
            .where(
                Job.original_backup_path.is_not(None),
                Job.backup_deleted_at.is_(None),
                Job.backup_restored_at.is_(None),
            )
            .options(joinedload(Job.tracked_file), joinedload(Job.plan_snapshot))
            .order_by(desc(Job.completed_at), desc(Job.updated_at))
        )
        query = _apply_backup_search(query, search)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        jobs = list(self.session.scalars(query))
        if include_missing:
            return jobs
        from pathlib import Path

        return [job for job in jobs if job.original_backup_path and Path(job.original_backup_path).exists()]

    def count_backup_jobs(self, *, search: str | None = None) -> int:
        query = (
            select(func.count(Job.id))
            .outerjoin(Job.tracked_file)
            .where(
                Job.original_backup_path.is_not(None),
                Job.backup_deleted_at.is_(None),
                Job.backup_restored_at.is_(None),
            )
        )
        query = _apply_backup_search(query, search)
        return int(self.session.scalar(query) or 0)

    def cleanup_expired_backups(self, *, now: datetime | None = None) -> list[Job]:
        from pathlib import Path

        effective_now = _normalise_datetime(now or datetime.now(timezone.utc))
        query = (
            select(Job)
            .where(
                Job.status == JobStatus.COMPLETED,
                Job.replacement_status == ReplacementStatus.SUCCEEDED,
                Job.backup_policy == "keep_for_1_day",
                Job.backup_retention_until.is_not(None),
                Job.backup_retention_until <= effective_now,
                Job.original_backup_path.is_not(None),
                Job.backup_deleted_at.is_(None),
                Job.backup_restored_at.is_(None),
            )
            .options(joinedload(Job.tracked_file), joinedload(Job.plan_snapshot))
            .order_by(asc(Job.backup_retention_until), asc(Job.updated_at))
        )
        deleted: list[Job] = []
        for job in self.session.scalars(query):
            backup_path = Path(str(job.original_backup_path))
            if not backup_path.exists() or backup_path.is_dir():
                continue
            backup_path.unlink()
            job.backup_deleted_at = effective_now
            deleted.append(job)
        if deleted:
            self.session.flush()
        return deleted

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
                        JobStatus.INTERRUPTED,
                        JobStatus.CANCELLED,
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


def _apply_backup_search(query: Select, search: str | None) -> Select:
    cleaned = (search or "").strip().lower()
    if not cleaned:
        return query
    pattern = f"%{cleaned}%"
    return query.where(
        or_(
            func.lower(Job.original_backup_path).like(pattern),
            func.lower(TrackedFile.source_path).like(pattern),
            func.lower(TrackedFile.source_filename).like(pattern),
        )
    )


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


def normalise_backup_policy(value: str | None) -> str:
    cleaned = (value or "keep").strip().lower()
    aliases = {
        "keep_backup": "keep",
        "keep": "keep",
        "delete_after_success": "delete_after_success",
        "delete_backup_after_success": "delete_after_success",
        "no_backup": "delete_after_success",
        "keep_for_1_day": "keep_for_1_day",
        "keep_for_one_day": "keep_for_1_day",
    }
    return aliases.get(cleaned, "keep")


def delete_replaced_source_for_backup_policy(value: str, *, fallback: bool) -> bool:
    policy = normalise_backup_policy(value)
    if policy == "delete_after_success":
        return True
    if policy in {"keep", "keep_for_1_day"}:
        return False
    return fallback


def job_requires_manual_review(job: Job) -> bool:
    tracked_file = job.tracked_file
    plan_snapshot = job.plan_snapshot
    return bool(
        tracked_file is not None
        and (
            tracked_file.operator_protected
            or tracked_file.is_protected
            or plan_snapshot.action.value == "manual_review"
            or plan_snapshot.should_treat_as_protected
        )
    )


def calculate_space_saved(
    input_size_bytes: int | None,
    output_size_bytes: int | None,
) -> int | None:
    if input_size_bytes is None or output_size_bytes is None:
        return None
    return input_size_bytes - output_size_bytes


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
