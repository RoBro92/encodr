from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session, joinedload

from encodr_db.models import (
    ComplianceState,
    FileLifecycleState,
    Job,
    JobStatus,
    PlanSnapshot,
    ProbeSnapshot,
    ReplacementStatus,
    TrackedFile,
    VerificationStatus,
)


@dataclass(frozen=True, slots=True)
class StorageSummary:
    total_original_size_bytes: int
    total_output_size_bytes: int
    total_space_saved_bytes: int
    average_space_saved_bytes: int | None
    average_space_saved_per_day_bytes: int | None
    measurable_job_count: int
    measurable_completed_job_count: int
    savings_by_action: dict[str, dict[str, int | None]]


@dataclass(frozen=True, slots=True)
class ProcessingHistorySummary:
    processed_file_count: int
    average_processed_per_day: float | None
    total_audio_tracks_removed: int
    total_subtitle_tracks_removed: int


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_tracked_files(self) -> int:
        return int(self.session.scalar(select(func.count(TrackedFile.id))) or 0)

    def count_files_by_lifecycle(self) -> dict[str, int]:
        return self._count_grouped(TrackedFile.lifecycle_state)

    def count_files_by_compliance(self) -> dict[str, int]:
        return self._count_grouped(TrackedFile.compliance_state)

    def count_jobs(self) -> int:
        return int(self.session.scalar(select(func.count(Job.id))) or 0)

    def count_jobs_by_status(self) -> dict[str, int]:
        return self._count_grouped(Job.status)

    def count_plans_by_action(self) -> dict[str, int]:
        return self._count_grouped(PlanSnapshot.action)

    def count_verification_outcomes(self) -> dict[str, int]:
        return self._count_grouped(Job.verification_status)

    def count_replacement_outcomes(self) -> dict[str, int]:
        return self._count_grouped(Job.replacement_status)

    def count_processed_under_policy(self, policy_version: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(TrackedFile.id)).where(
                    TrackedFile.last_processed_policy_version == policy_version,
                    TrackedFile.lifecycle_state == FileLifecycleState.COMPLETED,
                )
            )
            or 0
        )

    def count_protected_files(self) -> int:
        return int(
            self.session.scalar(
                select(func.count(TrackedFile.id)).where(TrackedFile.is_protected.is_(True))
            )
            or 0
        )

    def count_four_k_files(self) -> int:
        return int(
            self.session.scalar(select(func.count(TrackedFile.id)).where(TrackedFile.is_4k.is_(True)))
            or 0
        )

    def summarise_storage_outcomes(self) -> StorageSummary:
        jobs = list(
            self.session.scalars(
                select(Job)
                .options(joinedload(Job.plan_snapshot))
                .where(
                    Job.input_size_bytes.is_not(None),
                    Job.output_size_bytes.is_not(None),
                )
            )
        )
        total_original = sum(job.input_size_bytes or 0 for job in jobs)
        total_output = sum(job.output_size_bytes or 0 for job in jobs)
        total_saved = sum(job.space_saved_bytes or 0 for job in jobs)
        measurable_completed_jobs = [job for job in jobs if job.status == JobStatus.COMPLETED]
        savings_by_action: dict[str, dict[str, int | None]] = {}
        for action in ("remux", "transcode"):
            action_jobs = [
                job for job in measurable_completed_jobs if job.plan_snapshot.action.value == action
            ]
            action_saved = sum(job.space_saved_bytes or 0 for job in action_jobs)
            savings_by_action[action] = {
                "job_count": len(action_jobs),
                "space_saved_bytes": action_saved,
                "average_space_saved_bytes": (
                    int(action_saved / len(action_jobs)) if action_jobs else None
                ),
            }

        average_saved = int(total_saved / len(measurable_completed_jobs)) if measurable_completed_jobs else None
        average_saved_per_day = self._average_saved_per_day(measurable_completed_jobs)
        return StorageSummary(
            total_original_size_bytes=total_original,
            total_output_size_bytes=total_output,
            total_space_saved_bytes=total_saved,
            average_space_saved_bytes=average_saved,
            average_space_saved_per_day_bytes=average_saved_per_day,
            measurable_job_count=len(jobs),
            measurable_completed_job_count=len(measurable_completed_jobs),
            savings_by_action=savings_by_action,
        )

    def summarise_processing_history(self) -> ProcessingHistorySummary:
        processed_jobs = list(
            self.session.scalars(
                select(Job).where(
                    Job.status.in_([JobStatus.COMPLETED, JobStatus.SKIPPED]),
                    Job.completed_at.is_not(None),
                )
            )
        )
        return ProcessingHistorySummary(
            processed_file_count=len(processed_jobs),
            average_processed_per_day=self._average_count_per_day(processed_jobs),
            total_audio_tracks_removed=sum(
                self._analysis_count(job, "audio_tracks_removed_count") for job in processed_jobs
            ),
            total_subtitle_tracks_removed=sum(
                self._analysis_count(job, "subtitle_tracks_removed_count") for job in processed_jobs
            ),
        )

    def top_failure_categories(self, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(
                Job.failure_category,
                func.count(Job.id),
                func.max(Job.failure_message),
            )
            .where(Job.status == JobStatus.FAILED, Job.failure_category.is_not(None))
            .group_by(Job.failure_category)
            .order_by(desc(func.count(Job.id)), Job.failure_category.asc())
            .limit(limit)
        ).all()
        return [
            {
                "category": category,
                "count": count,
                "sample_message": sample_message,
            }
            for category, count, sample_message in rows
        ]

    def recent_jobs(
        self,
        *,
        limit: int = 10,
        statuses: list[JobStatus] | None = None,
    ) -> list[Job]:
        query: Select[tuple[Job]] = (
            select(Job)
            .options(joinedload(Job.plan_snapshot), joinedload(Job.tracked_file))
            .order_by(desc(Job.updated_at))
            .limit(limit)
        )
        if statuses:
            query = query.where(Job.status.in_(statuses))
        return list(self.session.scalars(query))

    def recent_completed_jobs(self, *, limit: int = 5) -> list[Job]:
        return self.recent_jobs(limit=limit, statuses=[JobStatus.COMPLETED, JobStatus.SKIPPED])

    def recent_failed_jobs(self, *, limit: int = 5) -> list[Job]:
        return self.recent_jobs(limit=limit, statuses=[JobStatus.FAILED, JobStatus.MANUAL_REVIEW])

    def list_latest_probe_snapshots(self) -> list[ProbeSnapshot]:
        return list(self.session.scalars(self._latest_snapshot_query(ProbeSnapshot)))

    def list_latest_plan_snapshots(self) -> list[PlanSnapshot]:
        return list(self.session.scalars(self._latest_snapshot_query(PlanSnapshot)))

    def action_breakdown_by_four_k(self) -> dict[str, dict[str, int]]:
        rows = self.session.execute(
            select(PlanSnapshot.action, TrackedFile.is_4k, func.count(PlanSnapshot.id))
            .join(TrackedFile, TrackedFile.id == PlanSnapshot.tracked_file_id)
            .group_by(PlanSnapshot.action, TrackedFile.is_4k)
        ).all()
        breakdown: dict[str, dict[str, int]] = {"4k": {}, "non_4k": {}}
        for action, is_4k, count in rows:
            bucket = "4k" if is_4k else "non_4k"
            breakdown[bucket][action.value] = int(count)
        return breakdown

    def _latest_snapshot_query(self, model):
        grouped = (
            select(model.tracked_file_id, func.max(model.created_at).label("latest_created_at"))
            .group_by(model.tracked_file_id)
            .subquery()
        )
        return (
            select(model)
            .join(
                grouped,
                (model.tracked_file_id == grouped.c.tracked_file_id)
                & (model.created_at == grouped.c.latest_created_at),
            )
            .order_by(desc(model.created_at))
        )

    def _count_grouped(self, column) -> dict[str, int]:
        rows = self.session.execute(
            select(column, func.count()).group_by(column).order_by(column.asc())
        ).all()
        result: dict[str, int] = {}
        for key, count in rows:
            name = key.value if hasattr(key, "value") else str(key)
            result[name] = int(count)
        return result

    def _average_saved_per_day(self, jobs: list[Job]) -> int | None:
        dated_jobs = [job for job in jobs if job.completed_at is not None]
        if not dated_jobs:
            return None
        total_saved = sum(job.space_saved_bytes or 0 for job in dated_jobs)
        return int(total_saved / self._date_span_days(dated_jobs))

    def _average_count_per_day(self, jobs: list[Job]) -> float | None:
        if not jobs:
            return None
        return len(jobs) / self._date_span_days(jobs)

    def _date_span_days(self, jobs: list[Job]) -> int:
        completed_dates = [job.completed_at.date() for job in jobs if job.completed_at is not None]
        if not completed_dates:
            return 1
        return max(1, (max(completed_dates) - min(completed_dates)).days + 1)

    def _analysis_count(self, job: Job, key: str) -> int:
        payload = job.analysis_payload
        if not isinstance(payload, dict):
            return 0
        value = payload.get(key)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
