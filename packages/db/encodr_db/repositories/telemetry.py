from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from encodr_db.models import Job, JobStatus, TelemetryAggregation

GLOBAL_AGGREGATION_KEY = "global"
COMPLETED_STATUSES = {JobStatus.COMPLETED, JobStatus.SKIPPED}
TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.INTERRUPTED,
    JobStatus.CANCELLED,
    JobStatus.SKIPPED,
    JobStatus.MANUAL_REVIEW,
}


class TelemetryAggregationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_rebuild_global(self) -> TelemetryAggregation:
        aggregation = self.session.get(TelemetryAggregation, GLOBAL_AGGREGATION_KEY)
        if aggregation is not None:
            return aggregation
        return self.rebuild_global()

    def rebuild_global(self) -> TelemetryAggregation:
        aggregation = self.session.get(TelemetryAggregation, GLOBAL_AGGREGATION_KEY)
        if aggregation is None:
            aggregation = TelemetryAggregation(key=GLOBAL_AGGREGATION_KEY)
            self.session.add(aggregation)

        self._reset(aggregation)
        jobs = list(
            self.session.scalars(
                select(Job)
                .options(joinedload(Job.plan_snapshot))
            )
        )
        for job in jobs:
            self._add_job(aggregation, job)
        self.session.flush()
        return aggregation

    def record_job_result(
        self,
        job: Job,
        *,
        previous_status: JobStatus | None,
    ) -> TelemetryAggregation:
        aggregation = self.session.get(TelemetryAggregation, GLOBAL_AGGREGATION_KEY)
        if aggregation is None or previous_status in TERMINAL_STATUSES:
            return self.rebuild_global()

        self._add_job(aggregation, job)
        self.session.flush()
        return aggregation

    def _reset(self, aggregation: TelemetryAggregation) -> None:
        aggregation.measurable_job_count = 0
        aggregation.measurable_completed_job_count = 0
        aggregation.processed_file_count = 0
        aggregation.total_original_size_bytes = 0
        aggregation.total_output_size_bytes = 0
        aggregation.total_space_saved_bytes = 0
        aggregation.completed_space_saved_bytes = 0
        aggregation.total_audio_tracks_removed = 0
        aggregation.total_subtitle_tracks_removed = 0
        aggregation.first_completed_at = None
        aggregation.last_completed_at = None
        aggregation.savings_by_action = _empty_savings_by_action()

    def _add_job(self, aggregation: TelemetryAggregation, job: Job) -> None:
        if job.input_size_bytes is not None and job.output_size_bytes is not None:
            aggregation.measurable_job_count += 1
            aggregation.total_original_size_bytes += int(job.input_size_bytes or 0)
            aggregation.total_output_size_bytes += int(job.output_size_bytes or 0)
            aggregation.total_space_saved_bytes += int(job.space_saved_bytes or 0)

        if job.status not in COMPLETED_STATUSES or job.completed_at is None:
            return

        aggregation.processed_file_count += 1
        completed_at = _normalise_datetime(job.completed_at)
        if aggregation.first_completed_at is None or completed_at < _normalise_datetime(aggregation.first_completed_at):
            aggregation.first_completed_at = completed_at
        if aggregation.last_completed_at is None or completed_at > _normalise_datetime(aggregation.last_completed_at):
            aggregation.last_completed_at = completed_at

        aggregation.total_audio_tracks_removed += _analysis_count(job, "audio_tracks_removed_count")
        aggregation.total_subtitle_tracks_removed += _analysis_count(job, "subtitle_tracks_removed_count")

        if job.input_size_bytes is None or job.output_size_bytes is None:
            return

        aggregation.measurable_completed_job_count += 1
        saved = int(job.space_saved_bytes or 0)
        aggregation.completed_space_saved_bytes += saved
        action = job.plan_snapshot.action.value if job.plan_snapshot is not None else "unknown"
        savings_by_action = dict(aggregation.savings_by_action or _empty_savings_by_action())
        bucket = dict(savings_by_action.get(action) or {"job_count": 0, "space_saved_bytes": 0})
        bucket["job_count"] = int(bucket.get("job_count") or 0) + 1
        bucket["space_saved_bytes"] = int(bucket.get("space_saved_bytes") or 0) + saved
        savings_by_action[action] = bucket
        aggregation.savings_by_action = savings_by_action


def _empty_savings_by_action() -> dict[str, dict[str, int]]:
    return {
        "remux": {"job_count": 0, "space_saved_bytes": 0},
        "transcode": {"job_count": 0, "space_saved_bytes": 0},
    }


def _analysis_count(job: Job, key: str) -> int:
    payload: Any = job.analysis_payload
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
