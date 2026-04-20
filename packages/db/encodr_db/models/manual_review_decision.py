from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, json_type, utcnow
from encodr_db.models.enums import ManualReviewDecisionType
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.job import Job
    from encodr_db.models.plan_snapshot import PlanSnapshot
    from encodr_db.models.tracked_file import TrackedFile
    from encodr_db.models.user import User


class ManualReviewDecision(Base, IdMixin):
    __tablename__ = "manual_review_decisions"
    __table_args__ = (
        Index("ix_manual_review_decisions_tracked_file_id_created_at", "tracked_file_id", "created_at"),
        Index("ix_manual_review_decisions_created_by_user_id_created_at", "created_by_user_id", "created_at"),
        Index("ix_manual_review_decisions_decision_type_created_at", "decision_type", "created_at"),
    )

    tracked_file_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_type: Mapped[ManualReviewDecisionType] = mapped_column(
        enum_type(ManualReviewDecisionType, "manual_review_decision_type"),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    details: Mapped[dict | None] = mapped_column(json_type())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tracked_file: Mapped["TrackedFile"] = relationship(back_populates="manual_review_decisions")
    plan_snapshot: Mapped["PlanSnapshot | None"] = relationship(back_populates="manual_review_decisions")
    job: Mapped["Job | None"] = relationship(back_populates="manual_review_decisions")
    created_by_user: Mapped["User"] = relationship(back_populates="manual_review_decisions")
