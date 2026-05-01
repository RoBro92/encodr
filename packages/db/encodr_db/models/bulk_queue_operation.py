from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from encodr_db.models.base import Base, IdMixin, TimestampMixin, json_type


class BulkQueueOperation(Base, IdMixin, TimestampMixin):
    __tablename__ = "bulk_queue_operations"
    __table_args__ = (
        Index("ix_bulk_queue_operations_status_updated_at", "status", "updated_at"),
        Index("ix_bulk_queue_operations_selection_hash", "selection_hash"),
        Index(
            "uq_bulk_queue_operations_one_active",
            text("1"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'cancelling')"),
            sqlite_where=text("status IN ('pending', 'running', 'cancelling')"),
        ),
    )

    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="scanning_selection")
    status_text: Mapped[str | None] = mapped_column(Text)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    total_expected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_batch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_batches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(json_type(), nullable=False)
    result_summary: Mapped[dict | None] = mapped_column(json_type())
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
