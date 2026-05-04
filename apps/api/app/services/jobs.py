from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.errors import ApiConflictError, ApiNotFoundError, ApiValidationError
from app.services.path_safety import (
    configured_path_roots,
    validate_backup_path,
    validate_final_output_path,
)
from encodr_core.config import ConfigBundle
from encodr_core.execution import ExecutionResult
from encodr_core.media import encodr_exclusion_reason
from encodr_core.planning import ProcessingPlan
from encodr_db.models import (
    ComplianceState,
    FileLifecycleState,
    Job,
    JobKind,
    JobStatus,
    ManualReviewDecisionType,
    PlanSnapshot,
    RETRYABLE_JOB_STATUSES,
    TrackedFile,
    User,
    WorkerType,
)
from encodr_db.repositories import JobRepository, ManualReviewDecisionRepository, TrackedFileRepository, WorkerRepository
from encodr_db.runtime import LocalWorkerLoop

logger = logging.getLogger("encodr.jobs")


class JobsService:
    def __init__(self, *, config_bundle: ConfigBundle | None = None) -> None:
        self.config_bundle = config_bundle

    def list_jobs(
        self,
        session: Session,
        *,
        status: JobStatus | None = None,
        status_group: str | None = None,
        job_kind: JobKind | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        search: str | None = None,
        include_cleared: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        return JobRepository(session).list_jobs(
            status=status,
            status_group=status_group,
            job_kind=job_kind,
            tracked_file_id=tracked_file_id,
            worker_name=worker_name,
            search=search,
            include_cleared=include_cleared,
            limit=limit,
            offset=offset,
        )

    def count_jobs(
        self,
        session: Session,
        *,
        status: JobStatus | None = None,
        status_group: str | None = None,
        job_kind: JobKind | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        search: str | None = None,
        include_cleared: bool = False,
    ) -> int:
        return JobRepository(session).count_jobs(
            status=status,
            status_group=status_group,
            job_kind=job_kind,
            tracked_file_id=tracked_file_id,
            worker_name=worker_name,
            search=search,
            include_cleared=include_cleared,
        )

    def list_progress_stream_jobs(
        self,
        session: Session,
        *,
        recent_terminal_since: datetime | None,
        limit: int = 100,
    ) -> list[Job]:
        return JobRepository(session).list_progress_stream_jobs(
            recent_terminal_since=recent_terminal_since,
            limit=limit,
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
        tracked_files = TrackedFileRepository(session)
        tracked_files.lock_for_update(tracked_file.id)
        session.refresh(tracked_file)
        self._validate_processable_target(tracked_file)
        repository = JobRepository(session)
        if repository.has_active_job_for_tracked_file(tracked_file.id):
            raise ApiConflictError("An active job already exists for this tracked file.")
        self._validate_review_gate(
            session,
            tracked_file=tracked_file,
            plan_snapshot=plan_snapshot,
            allow_review_approved=allow_review_approved,
        )
        job = self._create_job_from_plan(
            session,
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
                "event": "job_created",
                "job_id": job.id,
                "tracked_file_id": job.tracked_file_id,
                "file_id": job.tracked_file_id,
                "status": job.status.value,
                "job_kind": job.job_kind.value,
                "backup_policy": job.backup_policy,
            },
        )
        return job

    def retry_job(
        self,
        session: Session,
        *,
        job_id: str,
        existing_backup_strategy: str = "fail",
    ) -> Job:
        original_job = self.get_job(session, job_id=job_id)
        if original_job.status not in RETRYABLE_JOB_STATUSES:
            raise ApiConflictError(
                "Only failed, interrupted, cancelled, manual-review, or skipped jobs can be retried."
            )
        tracked_files = TrackedFileRepository(session)
        tracked_files.lock_for_update(original_job.tracked_file_id)
        session.refresh(original_job)
        if original_job.tracked_file is not None:
            session.refresh(original_job.tracked_file)
        self._validate_processable_target(original_job.tracked_file)
        self._validate_review_gate(
            session,
            tracked_file=original_job.tracked_file,
            plan_snapshot=original_job.plan_snapshot,
            allow_review_approved=False,
            operational_retry_job_id=(
                original_job.id
                if self._can_retry_operational_manual_review(original_job)
                else None
            ),
        )
        if existing_backup_strategy != "fail":
            self._validate_existing_backup_retry(original_job, existing_backup_strategy)
        repository = JobRepository(session)
        if repository.has_active_job_for_tracked_file(original_job.tracked_file_id):
            raise ApiConflictError("An active job already exists for this tracked file.")
        plan_snapshot = self._plan_snapshot_for_retry(
            session,
            original_job=original_job,
            existing_backup_strategy=existing_backup_strategy,
        )
        retry = self._create_job_from_plan(
            session,
            original_job.tracked_file,
            plan_snapshot,
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
        repository.mark_cleared(
            original_job,
            cleared_at=datetime.now(timezone.utc),
            reason="Retry job created by operator.",
        )

        logger.info(
            "job retried",
            extra={
                "event": "job_retried",
                "job_id": retry.id,
                "tracked_file_id": retry.tracked_file_id,
                "file_id": retry.tracked_file_id,
                "status": retry.status.value,
                "original_job_id": original_job.id,
                "existing_backup_strategy": existing_backup_strategy,
            },
        )
        return retry

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
            logger.info(
                "queued job cancelled",
                extra={
                    "event": "job_cancelled",
                    "job_id": job.id,
                    "tracked_file_id": job.tracked_file_id,
                    "file_id": job.tracked_file_id,
                    "status": job.status.value,
                    "reason": "cancelled_by_operator",
                },
            )
            return job

        assigned_worker = (
            WorkerRepository(session).get_by_id(job.assigned_worker_id)
            if job.assigned_worker_id is not None
            else None
        )
        if assigned_worker is not None and assigned_worker.worker_type != WorkerType.LOCAL:
            if job.cancellation_requested_at is not None:
                return job
            jobs.mark_cancellation_requested(
                job,
                requested_at=cancelled_at,
                reason="Cancellation requested for the remote worker.",
            )
            logger.warning(
                "remote job cancellation requested",
                extra={
                    "event": "job_cancellation_requested",
                    "job_id": job.id,
                    "tracked_file_id": job.tracked_file_id,
                    "file_id": job.tracked_file_id,
                    "worker_id": job.assigned_worker_id,
                    "status": job.status.value,
                    "reason": "remote_worker_cancellation_requested",
                },
            )
            return job
        if job.job_kind == JobKind.DRY_RUN:
            raise ApiConflictError("Running dry run analysis cannot yet be cancelled safely.")
        if not local_worker_loop.request_cancel(job.id):
            raise ApiConflictError("The local worker is not actively processing this job.")
        jobs.mark_cancelling(job, requested_at=cancelled_at)
        logger.info(
            "local running job cancellation requested",
            extra={
                "event": "job_cancellation_requested",
                "job_id": job.id,
                "tracked_file_id": job.tracked_file_id,
                "file_id": job.tracked_file_id,
                "status": job.status.value,
                "reason": "local_worker_cancellation_requested",
            },
        )
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
        logger.info(
            "queue cleared",
            extra={
                "event": "job_queue_cleared",
                "status": "cleared",
                "affected_count": len(cancelled),
                "job_ids": [job.id for job in cancelled],
            },
        )
        return cancelled

    def clear_failed_history(self, session: Session, *, job_ids: list[str] | None = None) -> list[Job]:
        if job_ids == []:
            logger.info(
                "failed job history clear skipped for empty selection",
                extra={"event": "failed_job_history_clear_skipped", "status": "skipped", "reason": "empty_selection"},
            )
            return []
        jobs = JobRepository(session).clear_failed_history(
            cleared_at=datetime.now(timezone.utc),
            job_ids=job_ids,
        )
        logger.info(
            "failed job history cleared",
            extra={
                "event": "failed_job_history_cleared",
                "status": "cleared",
                "affected_count": len(jobs),
                "job_ids": [job.id for job in jobs],
            },
        )
        return jobs

    def resolve_problem_jobs(
        self,
        session: Session,
        *,
        job_ids: list[str],
        action: str,
        existing_backup_strategy: str = "fail",
    ) -> list[Job]:
        if not job_ids:
            raise ApiValidationError("Select at least one failed or cancelled job.")
        if action not in {"retry", "skip"}:
            raise ApiValidationError("Unsupported failed job resolution action.")
        if action != "retry" and existing_backup_strategy != "fail":
            raise ApiValidationError("Backup handling options are only available when retrying failed jobs.")

        selected_jobs = self._selected_problem_jobs(session, job_ids=job_ids)
        error_keys = {_job_problem_error_key(job) for job in selected_jobs}
        if len(error_keys) > 1:
            logger.warning(
                "problem job bulk resolution rejected for mixed errors",
                extra={"job_ids": job_ids, "error_keys": sorted(error_keys), "action": action},
            )
            raise ApiConflictError("Select jobs with the same error before using a bulk action.")

        if action == "retry":
            return self._retry_problem_jobs(
                session,
                selected_jobs,
                existing_backup_strategy=existing_backup_strategy,
            )
        return self._mark_problem_jobs_skipped(session, selected_jobs)

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
        jobs = JobRepository(session).cleanup_expired_backups(
            now=now,
            path_validator=self._validate_cleanup_backup_path,
        )
        if jobs:
            logger.info(
                "expired backups deleted",
                extra={
                    "event": "expired_backups_deleted",
                    "status": "deleted",
                    "affected_count": len(jobs),
                    "job_ids": [job.id for job in jobs],
                },
            )
        return jobs

    def delete_backup(self, session: Session, *, job_id: str) -> Job:
        job = self.get_job(session, job_id=job_id)
        backup_path = self._backup_path_for_job(job)
        if not backup_path.exists() or backup_path.is_dir():
            raise ApiNotFoundError("Backup file could not be found.")
        backup_path = self._backup_path_for_job(job)
        backup_path.unlink()
        job.backup_deleted_at = datetime.now(timezone.utc)
        logger.info(
            "backup deleted",
            extra={
                "event": "backup_deleted",
                "job_id": job.id,
                "tracked_file_id": job.tracked_file_id,
                "file_id": job.tracked_file_id,
                "status": "deleted",
                "backup_path": backup_path.as_posix(),
            },
        )
        session.flush()
        return job

    def restore_backup(self, session: Session, *, job_id: str, restored_by_user: User | None = None) -> Job:
        job = self.get_job(session, job_id=job_id)
        tracked_files = TrackedFileRepository(session)
        tracked_files.lock_for_update(job.tracked_file_id)
        session.refresh(job)
        if job.tracked_file is not None:
            session.refresh(job.tracked_file)
        if JobRepository(session).has_active_job_for_tracked_file(job.tracked_file_id):
            raise ApiConflictError("An active job exists for this tracked file; restore the backup after it finishes.")
        backup_path = self._backup_path_for_job(job)
        if not backup_path.exists() or backup_path.is_dir():
            raise ApiNotFoundError("Backup file could not be found.")
        source_path = self._media_path(job.tracked_file.source_path, label="source_path")
        replacement_path = self._media_path(
            job.final_output_path or job.tracked_file.source_path,
            label="final_output_path",
        )
        if source_path.exists() and source_path != replacement_path:
            raise ApiConflictError("The original path is occupied and cannot be restored safely.")
        if source_path == replacement_path:
            backup_path.replace(source_path)
        else:
            backup_path.rename(source_path)
            if replacement_path.exists():
                try:
                    replacement_path.unlink()
                except OSError:
                    logger.warning(
                        "backup restored but replacement output could not be deleted",
                        extra={
                            "job_id": job.id,
                            "replacement_path": replacement_path.as_posix(),
                        },
                    )
        restored_at = datetime.now(timezone.utc)
        job.backup_restored_at = restored_at
        job.tracked_file.lifecycle_state = FileLifecycleState.MANUAL_REVIEW
        job.tracked_file.compliance_state = ComplianceState.MANUAL_REVIEW
        job.tracked_file.last_processed_policy_version = None
        job.tracked_file.last_processed_profile_name = None
        if restored_by_user is not None:
            ManualReviewDecisionRepository(session).add_decision(
                tracked_file_id=job.tracked_file_id,
                created_by_user=restored_by_user,
                decision_type=ManualReviewDecisionType.HELD,
                plan_snapshot_id=job.plan_snapshot_id,
                job_id=job.id,
                note="Restored from backup; review whether to skip or reprocess.",
                details={
                    "backup_path": backup_path.as_posix(),
                    "restored_source_path": source_path.as_posix(),
                    "restored_at": restored_at.isoformat(),
                },
            )
        logger.warning(
            "backup restored and file returned to manual review",
            extra={
                "event": "backup_restored",
                "job_id": job.id,
                "tracked_file_id": job.tracked_file_id,
                "file_id": job.tracked_file_id,
                "status": "restored",
                "backup_path": backup_path.as_posix(),
            },
        )
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
        try:
            TrackedFileRepository(session).lock_for_update(tracked_file.id)
            session.refresh(tracked_file)
            self._validate_processable_target(tracked_file)
        except ApiConflictError:
            return None
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
        try:
            return self._create_job_from_plan(
                session,
                tracked_file,
                plan_snapshot,
                preferred_worker_id=preferred_worker_id,
                pinned_worker_id=pinned_worker_id,
                preferred_backend_override=preferred_backend_override,
                schedule_windows=schedule_windows,
                watched_job_id=watched_job_id,
            )
        except ApiConflictError:
            return None

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

    @staticmethod
    def _validate_processable_target(tracked_file: TrackedFile) -> None:
        reason = encodr_exclusion_reason(tracked_file.source_path)
        if reason is not None:
            raise ApiConflictError(reason)

    def _validate_review_gate(
        self,
        session: Session,
        *,
        tracked_file: TrackedFile,
        plan_snapshot: PlanSnapshot,
        allow_review_approved: bool,
        operational_retry_job_id: str | None = None,
    ) -> None:
        latest_job = JobRepository(session).get_latest_for_tracked_file(tracked_file.id)
        latest_decision = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(tracked_file.id)
        protected_or_planner_review_required = bool(
            tracked_file.operator_protected
            or tracked_file.is_protected
            or plan_snapshot.action.value == "manual_review"
            or plan_snapshot.should_treat_as_protected
        )
        latest_job_requires_review = bool(
            latest_job is not None
            and latest_job.status == JobStatus.MANUAL_REVIEW
        )
        if (
            operational_retry_job_id is not None
            and latest_job is not None
            and latest_job.id == operational_retry_job_id
            and latest_job_requires_review
            and not protected_or_planner_review_required
        ):
            return
        requires_review = bool(
            protected_or_planner_review_required
            or latest_job_requires_review
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
    def _can_retry_operational_manual_review(job: Job) -> bool:
        return job.status == JobStatus.MANUAL_REVIEW and job.failure_category == "replacement_failed"

    @staticmethod
    def _validate_existing_backup_retry(job: Job, existing_backup_strategy: str) -> None:
        if existing_backup_strategy not in {"replace_backup", "keep_existing_backup"}:
            raise ApiValidationError("Unsupported backup handling option for retry.")
        if not _job_failed_because_backup_already_exists(job):
            logger.warning(
                "backup retry rejected for non-backup failure",
                extra={"job_id": job.id, "failure_category": job.failure_category},
            )
            raise ApiConflictError(
                "Backup handling options are only available for jobs that failed because a backup already exists."
            )
        if not job.original_backup_path:
            logger.warning("backup retry rejected because backup path is not recorded", extra={"job_id": job.id})
            raise ApiConflictError("The existing backup file is no longer recorded for this job.")
        backup_path = Path(job.original_backup_path)
        if job.tracked_file is not None:
            source_path = Path(job.tracked_file.source_path)
            expected_backup_path = source_path.with_name(
                f"{source_path.stem}.encodr-backup{source_path.suffix}"
            )
            if backup_path != expected_backup_path:
                logger.warning(
                    "backup retry rejected because recorded backup path was unexpected",
                    extra={
                        "job_id": job.id,
                        "backup_path": backup_path.as_posix(),
                        "expected_backup_path": expected_backup_path.as_posix(),
                    },
                )
                raise ApiConflictError("The recorded backup path does not match the expected source backup.")
        if not backup_path.exists():
            logger.warning(
                "backup retry rejected because backup file is missing",
                extra={"job_id": job.id, "backup_path": backup_path.as_posix()},
            )
            raise ApiConflictError("The existing backup file is no longer available.")

    def _selected_problem_jobs(self, session: Session, *, job_ids: list[str]) -> list[Job]:
        jobs_by_id: dict[str, Job] = {}
        for job_id in job_ids:
            job = JobRepository(session).get_by_id(job_id)
            if job is None:
                raise ApiNotFoundError("One or more selected jobs could not be found.")
            if job.status not in RETRYABLE_JOB_STATUSES:
                raise ApiConflictError("Only failed, interrupted, cancelled, manual-review, or skipped jobs can be resolved.")
            jobs_by_id[job.id] = job
        return [jobs_by_id[job_id] for job_id in job_ids if job_id in jobs_by_id]

    def _retry_problem_jobs(
        self,
        session: Session,
        selected_jobs: list[Job],
        *,
        existing_backup_strategy: str = "fail",
    ) -> list[Job]:
        retry_targets: dict[str, Job] = {}
        for job in selected_jobs:
            current = retry_targets.get(job.tracked_file_id)
            if current is None or self._normalise_datetime(job.updated_at) > self._normalise_datetime(current.updated_at):
                retry_targets[job.tracked_file_id] = job

        retried_jobs: list[Job] = []
        for job in retry_targets.values():
            retried_jobs.append(
                self.retry_job(
                    session,
                    job_id=job.id,
                    existing_backup_strategy=existing_backup_strategy,
                )
            )

        cleared_at = datetime.now(timezone.utc)
        repository = JobRepository(session)
        for job in selected_jobs:
            repository.mark_cleared(job, cleared_at=cleared_at, reason="Requeued by operator.")

        logger.info(
            "problem jobs requeued by operator",
            extra={
                "selected_job_ids": [job.id for job in selected_jobs],
                "requeued_job_ids": [job.id for job in retried_jobs],
                "selected_count": len(selected_jobs),
                "requeued_count": len(retried_jobs),
                "existing_backup_strategy": existing_backup_strategy,
            },
        )
        return retried_jobs

    def _mark_problem_jobs_skipped(self, session: Session, selected_jobs: list[Job]) -> list[Job]:
        skipped_at = datetime.now(timezone.utc)
        jobs = JobRepository(session)
        tracked_files = TrackedFileRepository(session)
        for job in selected_jobs:
            result = ExecutionResult(
                mode="operator_skip",
                status="skipped",
                original_backup_path=Path(job.original_backup_path) if job.original_backup_path else None,
                failure_message="Skipped by operator.",
                failure_category="operator_skipped",
                requested_backend=job.requested_execution_backend,
                actual_backend=job.actual_execution_backend,
                actual_accelerator=job.actual_execution_accelerator,
                backend_fallback_used=job.backend_fallback_used,
                backend_selection_reason="Skipped by operator from failed jobs bulk action.",
                started_at=skipped_at,
                completed_at=skipped_at,
            )
            jobs.mark_result(job, result)
            tracked_files.update_file_state_from_execution_result(
                job.tracked_file,
                ProcessingPlan.model_validate(job.plan_snapshot.payload),
                result,
            )

        logger.info(
            "problem jobs marked skipped by operator",
            extra={"job_ids": [job.id for job in selected_jobs], "affected_count": len(selected_jobs)},
        )
        return selected_jobs

    def _plan_snapshot_for_retry(
        self,
        session: Session,
        *,
        original_job: Job,
        existing_backup_strategy: str,
    ) -> PlanSnapshot:
        if existing_backup_strategy == "fail":
            return original_job.plan_snapshot
        if existing_backup_strategy not in {"replace_backup", "keep_existing_backup"}:
            raise ApiValidationError("Unsupported backup handling option for retry.")

        plan = ProcessingPlan.model_validate(original_job.plan_snapshot.payload)
        plan.replace.existing_backup_strategy = existing_backup_strategy
        snapshot = PlanSnapshot(
            tracked_file_id=original_job.tracked_file_id,
            probe_snapshot_id=original_job.plan_snapshot.probe_snapshot_id,
            action=plan.action,
            confidence=plan.confidence,
            policy_version=plan.policy_context.policy_version,
            profile_name=plan.policy_context.selected_profile_name,
            is_already_compliant=plan.is_already_compliant,
            should_treat_as_protected=plan.should_treat_as_protected,
            reasons=[reason.model_dump(mode="json") for reason in plan.reasons],
            warnings=[warning.model_dump(mode="json") for warning in plan.warnings],
            selected_streams=plan.selected_streams.model_dump(mode="json"),
            payload=plan.model_dump(mode="json"),
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    def _create_job_from_plan(
        self,
        session: Session,
        tracked_file: TrackedFile,
        plan_snapshot: PlanSnapshot,
        **kwargs,
    ) -> Job:
        repository = JobRepository(session)
        try:
            with session.begin_nested():
                return repository.create_job_from_plan(tracked_file, plan_snapshot, **kwargs)
        except IntegrityError as error:
            if repository.has_active_job_for_tracked_file(tracked_file.id):
                raise ApiConflictError("An active job already exists for this tracked file.") from error
            raise

    def _backup_path_for_job(self, job: Job) -> Path:
        backup_path = _backup_path_for_job(job)
        roots = self._path_roots()
        if roots is None:
            return backup_path
        safe_path = validate_backup_path(backup_path, roots, label="original_backup_path")
        if safe_path is None:
            raise ApiNotFoundError("No backup is recorded for this job.")
        return safe_path

    def _media_path(self, path: Path | str, *, label: str) -> Path:
        roots = self._path_roots()
        if roots is None:
            return Path(path)
        safe_path = validate_final_output_path(path, roots, label=label)
        if safe_path is None:
            raise ApiValidationError(f"{label} is required.")
        return safe_path

    def _validate_cleanup_backup_path(self, path: Path, job: Job) -> Path | None:
        roots = self._path_roots()
        if roots is None:
            return path
        try:
            return validate_backup_path(path, roots, label="original_backup_path")
        except ApiValidationError as error:
            logger.warning(
                "expired backup cleanup skipped unsafe path",
                extra={"job_id": job.id, "backup_path": str(path), "reason": str(error)},
            )
            return None

    def _path_roots(self):
        if self.config_bundle is None:
            return None
        return configured_path_roots(self.config_bundle)

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def _backup_path_for_job(job: Job) -> Path:
    if not job.original_backup_path:
        raise ApiNotFoundError("No backup is recorded for this job.")
    return Path(job.original_backup_path)


def _job_failed_because_backup_already_exists(job: Job) -> bool:
    replacement_payload = job.replacement_payload if isinstance(job.replacement_payload, dict) else {}
    details = replacement_payload.get("details") if isinstance(replacement_payload.get("details"), dict) else {}
    if details.get("failure_code") == "backup_already_exists":
        return True
    return (
        job.failure_category == "replacement_failed"
        and "backup file already exists" in (job.failure_message or "").lower()
    )


def _job_problem_error_key(job: Job) -> str:
    replacement_payload = job.replacement_payload if isinstance(job.replacement_payload, dict) else {}
    details = replacement_payload.get("details") if isinstance(replacement_payload.get("details"), dict) else {}
    code = details.get("failure_code") or job.failure_category or "unknown"
    message = _normalise_problem_message(
        " ".join(
            value
            for value in [
                job.failure_message,
                job.replacement_failure_message,
                job.interruption_reason,
            ]
            if value
        )
    )
    return f"{code}:{message}"


def _normalise_problem_message(value: str) -> str:
    return " ".join(value.strip().lower().split())
