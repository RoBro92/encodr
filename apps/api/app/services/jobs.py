from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
from typing import Callable

from sqlalchemy.orm import Session

from app.services.errors import ApiConflictError, ApiNotFoundError
from encodr_core.planning import ProcessingPlan
from encodr_db.models import (
    ComplianceState,
    FileLifecycleState,
    Job,
    JobKind,
    JobStatus,
    ManualReviewDecisionType,
    PlanSnapshot,
    TrackedFile,
    WorkerType,
)
from encodr_db.repositories import JobRepository, ManualReviewDecisionRepository, TrackedFileRepository, WorkerRepository
from encodr_db.runtime import LocalWorkerLoop

logger = logging.getLogger("encodr.jobs")


class JobsService:
    def list_jobs(
        self,
        session: Session,
        *,
        status: JobStatus | None = None,
        job_kind: JobKind | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        include_cleared: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        return JobRepository(session).list_jobs(
            status=status,
            job_kind=job_kind,
            tracked_file_id=tracked_file_id,
            worker_name=worker_name,
            include_cleared=include_cleared,
            limit=limit,
            offset=offset,
        )

    def get_job(self, session: Session, *, job_id: str) -> Job:
        job = JobRepository(session).get_by_id(job_id)
        if job is None:
            raise ApiNotFoundError("Job could not be found.")
        return job

    def create_job(
        self,
        session: Session,
        *,
        tracked_file_id: str | None = None,
        plan_snapshot_id: str | None = None,
        allow_review_approved: bool = False,
        preferred_worker_id: str | None = None,
        pinned_worker_id: str | None = None,
        preferred_backend_override: str | None = None,
        schedule_windows: list[dict] | None = None,
        watched_job_id: str | None = None,
        job_kind: JobKind = JobKind.EXECUTION,
        analysis_payload: dict | None = None,
        ignore_worker_schedule: bool = False,
        backup_policy: str = "keep",
    ) -> Job:
        tracked_file, plan_snapshot = self._resolve_target(
            session,
            tracked_file_id=tracked_file_id,
            plan_snapshot_id=plan_snapshot_id,
        )
        self._validate_review_gate(
            session,
            tracked_file=tracked_file,
            plan_snapshot=plan_snapshot,
            allow_review_approved=allow_review_approved,
        )
        job = JobRepository(session).create_job_from_plan(
            tracked_file,
            plan_snapshot,
            preferred_worker_id=preferred_worker_id,
            pinned_worker_id=pinned_worker_id,
            preferred_backend_override=preferred_backend_override,
            schedule_windows=schedule_windows,
            watched_job_id=watched_job_id,
            job_kind=job_kind,
            analysis_payload=analysis_payload,
            ignore_worker_schedule=ignore_worker_schedule,
            backup_policy=backup_policy,
        )
        logger.info(
            "job created",
            extra={
                "job_id": job.id,
                "tracked_file_id": job.tracked_file_id,
                "job_kind": job.job_kind.value,
                "backup_policy": job.backup_policy,
            },
        )
        return job

    def retry_job(self, session: Session, *, job_id: str) -> Job:
        original_job = self.get_job(session, job_id=job_id)
        if original_job.status not in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW, JobStatus.SKIPPED, JobStatus.INTERRUPTED, JobStatus.CANCELLED}:
            raise ApiConflictError("Only failed, interrupted, cancelled, manual-review, or skipped jobs can be retried.")
        self._validate_review_gate(
            session,
            tracked_file=original_job.tracked_file,
            plan_snapshot=original_job.plan_snapshot,
            allow_review_approved=False,
        )
        return JobRepository(session).create_job_from_plan(
            original_job.tracked_file,
            original_job.plan_snapshot,
            attempt_count=original_job.attempt_count + 1,
            preferred_worker_id=original_job.preferred_worker_id,
            pinned_worker_id=original_job.pinned_worker_id,
            preferred_backend_override=original_job.preferred_backend_override,
            schedule_windows=original_job.schedule_windows,
            watched_job_id=original_job.watched_job_id,
            job_kind=original_job.job_kind,
            analysis_payload=original_job.analysis_payload,
            ignore_worker_schedule=original_job.ignore_worker_schedule,
            backup_policy=original_job.backup_policy,
        )

    def cancel_job(
        self,
        session: Session,
        *,
        job_id: str,
        local_worker_loop: LocalWorkerLoop,
    ) -> Job:
        job = self.get_job(session, job_id=job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.SKIPPED, JobStatus.MANUAL_REVIEW}:
            raise ApiConflictError("This job can no longer be cancelled.")

        jobs = JobRepository(session)
        tracked_files = TrackedFileRepository(session)
        cancelled_at = datetime.now(timezone.utc)

        if job.status in {JobStatus.PENDING, JobStatus.SCHEDULED}:
            jobs.mark_cancelled(job, cancelled_at=cancelled_at)
            tracked_files.update_file_state_from_plan_result(
                job.tracked_file,
                ProcessingPlan.model_validate(job.plan_snapshot.payload),
            )
            logger.info("queued job cancelled", extra={"job_id": job.id, "status": job.status.value})
            return job

        assigned_worker = (
            WorkerRepository(session).get_by_id(job.assigned_worker_id)
            if job.assigned_worker_id is not None
            else None
        )
        if assigned_worker is not None and assigned_worker.worker_type != WorkerType.LOCAL:
            jobs.mark_cancellation_requested(
                job,
                requested_at=cancelled_at,
                reason=(
                    "Cancellation requested for the remote worker. The current worker agent "
                    "does not support safe in-flight process termination yet."
                ),
            )
            logger.warning("remote job cancellation requested", extra={"job_id": job.id, "worker_id": job.assigned_worker_id})
            return job
        if job.job_kind == JobKind.DRY_RUN:
            raise ApiConflictError("Running dry run analysis cannot yet be cancelled safely.")
        if not local_worker_loop.request_cancel(job.id):
            raise ApiConflictError("The local worker is not actively processing this job.")
        jobs.mark_cancelling(job, requested_at=cancelled_at)
        logger.info("local running job cancellation requested", extra={"job_id": job.id})
        return job

    def clear_queue(self, session: Session) -> list[Job]:
        cleared_at = datetime.now(timezone.utc)
        jobs = JobRepository(session)
        cancelled = jobs.clear_queue(cleared_at=cleared_at)
        tracked_files = TrackedFileRepository(session)
        for job in cancelled:
            tracked_files.update_file_state_from_plan_result(
                job.tracked_file,
                ProcessingPlan.model_validate(job.plan_snapshot.payload),
            )
        logger.info("queue cleared", extra={"affected_count": len(cancelled)})
        return cancelled

    def clear_failed_history(self, session: Session) -> list[Job]:
        jobs = JobRepository(session).clear_failed_history(cleared_at=datetime.now(timezone.utc))
        logger.info("failed job history cleared", extra={"affected_count": len(jobs)})
        return jobs

    def list_backups(
        self,
        session: Session,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        return JobRepository(session).list_backup_jobs(search=search, limit=limit, offset=offset)

    def count_backups(self, session: Session, *, search: str | None = None) -> int:
        return JobRepository(session).count_backup_jobs(search=search)

    def cleanup_expired_backups(self, session: Session, *, now: datetime | None = None) -> list[Job]:
        jobs = JobRepository(session).cleanup_expired_backups(now=now)
        if jobs:
            logger.info("expired backups deleted", extra={"affected_count": len(jobs)})
        return jobs

    def delete_backup(self, session: Session, *, job_id: str) -> Job:
        job = self.get_job(session, job_id=job_id)
        backup_path = _backup_path_for_job(job)
        if not backup_path.exists():
            raise ApiNotFoundError("Backup file could not be found.")
        backup_path.unlink()
        job.backup_deleted_at = datetime.now(timezone.utc)
        logger.info("backup deleted", extra={"job_id": job.id, "backup_path": backup_path.as_posix()})
        session.flush()
        return job

    def restore_backup(self, session: Session, *, job_id: str) -> Job:
        job = self.get_job(session, job_id=job_id)
        backup_path = _backup_path_for_job(job)
        if not backup_path.exists():
            raise ApiNotFoundError("Backup file could not be found.")
        source_path = Path(job.tracked_file.source_path)
        replacement_path = Path(job.final_output_path or job.tracked_file.source_path)
        if replacement_path.exists():
            restored_replacement = replacement_path.with_name(
                f"{replacement_path.stem}.encodr-restored-replacement{replacement_path.suffix}"
            )
            if restored_replacement.exists():
                raise ApiConflictError("A previous restored replacement file already exists.")
            shutil.move(replacement_path.as_posix(), restored_replacement.as_posix())
        if source_path.exists() and source_path != replacement_path:
            raise ApiConflictError("The original path is occupied and cannot be restored safely.")
        shutil.move(backup_path.as_posix(), source_path.as_posix())
        job.backup_restored_at = datetime.now(timezone.utc)
        job.tracked_file.lifecycle_state = FileLifecycleState.MANUAL_REVIEW
        job.tracked_file.compliance_state = ComplianceState.MANUAL_REVIEW
        job.tracked_file.last_processed_policy_version = None
        job.tracked_file.last_processed_profile_name = None
        logger.warning("backup restored and file returned to manual review", extra={"job_id": job.id, "backup_path": backup_path.as_posix()})
        session.flush()
        return job

    def create_batch_jobs(
        self,
        session: Session,
        *,
        planned_targets: list[tuple[str, TrackedFile, PlanSnapshot]],
        preferred_worker_id: str | None = None,
        pinned_worker_id: str | None = None,
        preferred_backend_override: str | None = None,
        schedule_windows: list[dict] | None = None,
        watched_job_id: str | None = None,
        job_kind: JobKind = JobKind.EXECUTION,
        analysis_payload_factory: Callable[[str, TrackedFile, PlanSnapshot], dict | None] | None = None,
        ignore_worker_schedule: bool = False,
        backup_policy: str = "keep",
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for source_path, tracked_file, plan_snapshot in planned_targets:
            try:
                job = self.create_job(
                    session,
                    tracked_file_id=tracked_file.id,
                    plan_snapshot_id=plan_snapshot.id,
                    preferred_worker_id=preferred_worker_id,
                    pinned_worker_id=pinned_worker_id,
                    preferred_backend_override=preferred_backend_override,
                    schedule_windows=schedule_windows,
                    watched_job_id=watched_job_id,
                    job_kind=job_kind,
                    analysis_payload=(
                        analysis_payload_factory(source_path, tracked_file, plan_snapshot)
                        if analysis_payload_factory is not None
                        else None
                    ),
                    ignore_worker_schedule=ignore_worker_schedule,
                    backup_policy=backup_policy,
                )
                results.append({
                    "source_path": source_path,
                    "status": "created",
                    "message": None,
                    "job": job,
                })
            except ApiConflictError as error:
                results.append({
                    "source_path": source_path,
                    "status": "blocked",
                    "message": str(error),
                    "job": None,
                })
        return results

    def create_watched_job_if_needed(
        self,
        session: Session,
        *,
        tracked_file: TrackedFile,
        plan_snapshot: PlanSnapshot,
        watched_job_id: str,
        preferred_worker_id: str | None,
        pinned_worker_id: str | None,
        preferred_backend_override: str | None,
        schedule_windows: list[dict] | None,
    ) -> Job | None:
        repository = JobRepository(session)
        if repository.has_active_job_for_tracked_file(tracked_file.id):
            return None
        try:
            self._validate_review_gate(
                session,
                tracked_file=tracked_file,
                plan_snapshot=plan_snapshot,
                allow_review_approved=False,
            )
        except ApiConflictError:
            return None
        return repository.create_job_from_plan(
            tracked_file,
            plan_snapshot,
            preferred_worker_id=preferred_worker_id,
            pinned_worker_id=pinned_worker_id,
            preferred_backend_override=preferred_backend_override,
            schedule_windows=schedule_windows,
            watched_job_id=watched_job_id,
        )

    def _resolve_target(
        self,
        session: Session,
        *,
        tracked_file_id: str | None,
        plan_snapshot_id: str | None,
    ) -> tuple[TrackedFile, PlanSnapshot]:
        tracked_files = TrackedFileRepository(session)
        if plan_snapshot_id is not None:
            plan_snapshot = session.get(PlanSnapshot, plan_snapshot_id)
            if plan_snapshot is None:
                raise ApiNotFoundError("Plan snapshot could not be found.")
            tracked_file = tracked_files.get_by_id(plan_snapshot.tracked_file_id)
            if tracked_file is None:
                raise ApiNotFoundError("Tracked file for the plan snapshot could not be found.")
            return tracked_file, plan_snapshot

        tracked_file = tracked_files.get_by_id(tracked_file_id or "")
        if tracked_file is None:
            raise ApiNotFoundError("Tracked file could not be found.")
        plan_snapshot = tracked_files.get_latest_plan_snapshot(tracked_file.id)
        if plan_snapshot is None:
            raise ApiConflictError("No plan snapshot exists for the tracked file.")
        return tracked_file, plan_snapshot

    def _validate_review_gate(
        self,
        session: Session,
        *,
        tracked_file: TrackedFile,
        plan_snapshot: PlanSnapshot,
        allow_review_approved: bool,
    ) -> None:
        latest_job = JobRepository(session).get_latest_for_tracked_file(tracked_file.id)
        latest_decision = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(tracked_file.id)
        if (
            latest_decision is not None
            and latest_decision.decision_type == ManualReviewDecisionType.EXCLUDED
            and self._normalise_datetime(latest_decision.created_at) >= self._normalise_datetime(plan_snapshot.created_at)
        ):
            raise ApiConflictError(
                "This file was excluded from future processing by an operator."
            )
        requires_review = bool(
            tracked_file.operator_protected
            or tracked_file.is_protected
            or plan_snapshot.action.value == "manual_review"
            or plan_snapshot.should_treat_as_protected
            or (
                latest_job is not None
                and latest_job.status == JobStatus.MANUAL_REVIEW
            )
        )
        if not requires_review:
            return

        issue_at_candidates = [plan_snapshot.created_at]
        if tracked_file.operator_protected_updated_at is not None:
            issue_at_candidates.append(tracked_file.operator_protected_updated_at)
        if latest_job is not None and latest_job.status == JobStatus.MANUAL_REVIEW:
            issue_at_candidates.append(latest_job.updated_at)
        issue_at = max(self._normalise_datetime(value) for value in issue_at_candidates)

        decision_is_current = (
            latest_decision is not None
            and latest_decision.decision_type == ManualReviewDecisionType.APPROVED
            and self._normalise_datetime(latest_decision.created_at) >= issue_at
            and latest_decision.plan_snapshot_id == plan_snapshot.id
        )

        if allow_review_approved and decision_is_current:
            return

        raise ApiConflictError(
            "This file requires manual review or protected-file approval before a job can be created."
        )

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def _backup_path_for_job(job: Job) -> Path:
    if not job.original_backup_path:
        raise ApiNotFoundError("No backup is recorded for this job.")
    return Path(job.original_backup_path)
