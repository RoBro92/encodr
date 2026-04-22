from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin, json_type

if TYPE_CHECKING:
    from encodr_db.models.watched_job_definition import WatchedJobDefinition


class ScanRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "scan_records"
    __table_args__ = (
        Index("ix_scan_records_scanned_at", "scanned_at"),
        Index("ix_scan_records_source_path", "source_path"),
        Index("ix_scan_records_watched_job_id", "watched_job_id"),
    )

    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    watched_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("watched_job_definitions.id", ondelete="SET NULL"),
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    directory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    direct_directory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likely_show_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likely_season_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likely_episode_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likely_film_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_payload: Mapped[list[dict]] = mapped_column(json_type(), nullable=False, default=list)

    watched_job: Mapped["WatchedJobDefinition | None"] = relationship(
        back_populates="scan_records",
        foreign_keys=[watched_job_id],
    )
