from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, json_type, TimestampMixin

if TYPE_CHECKING:
    from encodr_db.models.plan_snapshot import PlanSnapshot
    from encodr_db.models.tracked_file import TrackedFile


class ProbeSnapshot(Base, IdMixin, TimestampMixin):
    __tablename__ = "probe_snapshots"
    __table_args__ = (
        Index("ix_probe_snapshots_tracked_file_id_created_at", "tracked_file_id", "created_at"),
    )

    tracked_file_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)

    tracked_file: Mapped["TrackedFile"] = relationship(back_populates="probe_snapshots")
    plan_snapshots: Mapped[list["PlanSnapshot"]] = relationship(back_populates="probe_snapshot")
