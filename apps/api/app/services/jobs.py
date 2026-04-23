from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.services.errors import ApiConflictError, ApiNotFoundError
from encodr_db.models import Job, JobKind, JobStatus, ManualReviewDecisionType, PlanSnapshot, TrackedFile
from encodr_db.repositories import JobRepository, ManualReviewDecisionRepository, TrackedFileRepository


class JobsService:
    def list_jobs(
        self,
        session: Session,
        *,
        status: JobStatus | None = None,
        job_kind: JobKind | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        return JobRepository(session).list_jobs(
            status=status,
            job_kind=job_kind,
            tracked_file_id=tracked_file_id,
            worker_name=worker_name,
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
        )
        return job

    def retry_job(self, session: Session, *, job_id: str) -> Job:
        original_job = self.get_job(session, job_id=job_id)
        if original_job.status not in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW, JobStatus.SKIPPED, JobStatus.INTERRUPTED}:
            raise ApiConflictError("Only failed, interrupted, manual-review, or skipped jobs can be retried.")
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
        )

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

        latest_decision = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(tracked_file.id)
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
