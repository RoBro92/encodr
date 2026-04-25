from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from encodr_db.models.base import Base, TimestampMixin, json_type


class TelemetryAggregation(Base, TimestampMixin):
    __tablename__ = "telemetry_aggregations"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, default="global")
    measurable_job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    measurable_completed_job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_original_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_output_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_space_saved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completed_space_saved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_audio_tracks_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_subtitle_tracks_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    savings_by_action: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
