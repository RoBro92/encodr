from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin, json_type

if TYPE_CHECKING:
    from encodr_db.models.job import Job
    from encodr_db.models.scan_record import ScanRecord
    from encodr_db.models.worker import Worker


class WatchedJobDefinition(Base, IdMixin, TimestampMixin):
    __tablename__ = "watched_job_definitions"
    __table_args__ = (
        Index("ix_watched_job_definitions_enabled", "enabled"),
        Index("ix_watched_job_definitions_source_path", "source_path"),
    )

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    media_class: Mapped[str] = mapped_column(String(32), nullable=False, default="movie")
    ruleset_override: Mapped[str | None] = mapped_column(String(32))
    preferred_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"),
        index=True,
    )
    pinned_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"),
        index=True,
    )
    preferred_backend: Mapped[str | None] = mapped_column(String(64))
    schedule_windows: Mapped[list[dict] | None] = mapped_column(json_type())
    auto_queue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stage_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_scan_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("scan_records.id", ondelete="SET NULL"),
        index=True,
    )
    last_seen_paths: Mapped[list[str] | None] = mapped_column(json_type())
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enqueue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    preferred_worker: Mapped["Worker | None"] = relationship(foreign_keys=[preferred_worker_id])
    pinned_worker: Mapped["Worker | None"] = relationship(foreign_keys=[pinned_worker_id])
    last_scan_record: Mapped["ScanRecord | None"] = relationship(
        foreign_keys=[last_scan_record_id],
        post_update=True,
    )
    scan_records: Mapped[list["ScanRecord"]] = relationship(
        back_populates="watched_job",
        foreign_keys="ScanRecord.watched_job_id",
    )
    created_jobs: Mapped[list["Job"]] = relationship(back_populates="watched_job")
