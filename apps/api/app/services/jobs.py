from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.errors import ApiConflictError, ApiNotFoundError
from encodr_db.models import Job, JobStatus, PlanSnapshot, TrackedFile
from encodr_db.repositories import JobRepository, TrackedFileRepository


class JobsService:
    def list_jobs(
        self,
        session: Session,
        *,
        status: JobStatus | None = None,
        tracked_file_id: str | None = None,
        worker_name: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        return JobRepository(session).list_jobs(
            status=status,
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
    ) -> Job:
        tracked_file, plan_snapshot = self._resolve_target(
            session,
            tracked_file_id=tracked_file_id,
            plan_snapshot_id=plan_snapshot_id,
        )
        job = JobRepository(session).create_job_from_plan(tracked_file, plan_snapshot)
        return job

    def retry_job(self, session: Session, *, job_id: str) -> Job:
        original_job = self.get_job(session, job_id=job_id)
        if original_job.status not in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW, JobStatus.SKIPPED}:
            raise ApiConflictError("Only failed, manual-review, or skipped jobs can be retried.")
        return JobRepository(session).create_job_from_plan(
            original_job.tracked_file,
            original_job.plan_snapshot,
            attempt_count=original_job.attempt_count + 1,
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
