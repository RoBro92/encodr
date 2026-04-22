from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from encodr_db.models import WatchedJobDefinition


class WatchedJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, watched_job_id: str) -> WatchedJobDefinition | None:
        return self.session.get(WatchedJobDefinition, watched_job_id)

    def get_by_source_path(self, source_path: str) -> WatchedJobDefinition | None:
        query = select(WatchedJobDefinition).where(WatchedJobDefinition.source_path == source_path)
        return self.session.scalar(query)

    def list_watched_jobs(self, *, enabled: bool | None = None) -> list[WatchedJobDefinition]:
        query = select(WatchedJobDefinition).order_by(desc(WatchedJobDefinition.updated_at))
        if enabled is not None:
            query = query.where(WatchedJobDefinition.enabled.is_(enabled))
        return list(self.session.scalars(query))

    def create_or_update(
        self,
        *,
        watched_job_id: str | None,
        display_name: str,
        source_path: str,
        media_class: str,
        ruleset_override: str | None,
        preferred_worker_id: str | None,
        pinned_worker_id: str | None,
        preferred_backend: str | None,
        schedule_windows: list[dict] | None,
        auto_queue: bool,
        stage_only: bool,
        enabled: bool,
    ) -> WatchedJobDefinition:
        watched_job = self.get_by_id(watched_job_id) if watched_job_id is not None else None
        if watched_job is None:
            watched_job = self.get_by_source_path(source_path)
        if watched_job is None:
            watched_job = WatchedJobDefinition(
                display_name=display_name,
                source_path=source_path,
            )
            self.session.add(watched_job)

        watched_job.display_name = display_name
        watched_job.source_path = source_path
        watched_job.media_class = media_class
        watched_job.ruleset_override = ruleset_override
        watched_job.preferred_worker_id = preferred_worker_id
        watched_job.pinned_worker_id = pinned_worker_id
        watched_job.preferred_backend = preferred_backend
        watched_job.schedule_windows = schedule_windows
        watched_job.auto_queue = auto_queue
        watched_job.stage_only = stage_only
        watched_job.enabled = enabled
        self.session.flush()
        return watched_job

    def update_last_scan(
        self,
        watched_job: WatchedJobDefinition,
        *,
        last_scan_record_id: str | None,
        last_seen_paths: list[str],
        scanned_at: datetime,
        enqueue_at: datetime | None = None,
    ) -> WatchedJobDefinition:
        watched_job.last_scan_record_id = last_scan_record_id
        watched_job.last_seen_paths = list(last_seen_paths)
        watched_job.last_scan_at = scanned_at
        if enqueue_at is not None:
            watched_job.last_enqueue_at = enqueue_at
        self.session.flush()
        return watched_job
