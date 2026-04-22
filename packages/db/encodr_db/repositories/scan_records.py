from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from encodr_db.models import ScanRecord


class ScanRecordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_scan_record(
        self,
        *,
        source_path: str,
        root_path: str,
        source_kind: str,
        watched_job_id: str | None,
        directory_count: int,
        direct_directory_count: int,
        video_file_count: int,
        likely_show_count: int,
        likely_season_count: int,
        likely_episode_count: int,
        likely_film_count: int,
        files_payload: list[dict],
        stale: bool = False,
        scanned_at: datetime | None = None,
    ) -> ScanRecord:
        record = ScanRecord(
            source_path=source_path,
            root_path=root_path,
            source_kind=source_kind,
            watched_job_id=watched_job_id,
            scanned_at=scanned_at or datetime.now(timezone.utc),
            stale=stale,
            directory_count=directory_count,
            direct_directory_count=direct_directory_count,
            video_file_count=video_file_count,
            likely_show_count=likely_show_count,
            likely_season_count=likely_season_count,
            likely_episode_count=likely_episode_count,
            likely_film_count=likely_film_count,
            files_payload=files_payload,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_id(self, record_id: str) -> ScanRecord | None:
        return self.session.get(ScanRecord, record_id)

    def list_recent(self, *, limit: int = 20) -> list[ScanRecord]:
        query = select(ScanRecord).order_by(desc(ScanRecord.scanned_at)).limit(limit)
        return list(self.session.scalars(query))

    def mark_stale(self, record: ScanRecord, *, stale: bool) -> ScanRecord:
        record.stale = stale
        self.session.flush()
        return record
