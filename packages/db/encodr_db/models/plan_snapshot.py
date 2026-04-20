from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_core.planning.enums import ConfidenceLevel, PlanAction
from encodr_db.models.base import Base, IdMixin, json_type, TimestampMixin
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.job import Job
    from encodr_db.models.probe_snapshot import ProbeSnapshot
    from encodr_db.models.tracked_file import TrackedFile


class PlanSnapshot(Base, IdMixin, TimestampMixin):
    __tablename__ = "plan_snapshots"
    __table_args__ = (
        Index("ix_plan_snapshots_tracked_file_id_created_at", "tracked_file_id", "created_at"),
    )

    tracked_file_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    probe_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("probe_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[PlanAction] = mapped_column(
        enum_type(PlanAction, "plan_action"),
        nullable=False,
    )
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        enum_type(ConfidenceLevel, "plan_confidence"),
        nullable=False,
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_name: Mapped[str | None] = mapped_column(String(255))
    is_already_compliant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    should_treat_as_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(json_type(), nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(json_type(), nullable=False)
    selected_streams: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)

    tracked_file: Mapped["TrackedFile"] = relationship(back_populates="plan_snapshots")
    probe_snapshot: Mapped["ProbeSnapshot"] = relationship(back_populates="plan_snapshots")
    jobs: Mapped[list["Job"]] = relationship(back_populates="plan_snapshot")
