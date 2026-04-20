from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin
from encodr_db.models.enums import ComplianceState, FileLifecycleState
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.job import Job
    from encodr_db.models.plan_snapshot import PlanSnapshot
    from encodr_db.models.probe_snapshot import ProbeSnapshot


class TrackedFile(Base, IdMixin, TimestampMixin):
    __tablename__ = "tracked_files"
    __table_args__ = (
        Index("ix_tracked_files_created_at", "created_at"),
        Index("ix_tracked_files_updated_at", "updated_at"),
    )

    source_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_extension: Mapped[str | None] = mapped_column(String(32))
    source_directory: Mapped[str] = mapped_column(Text, nullable=False)
    last_observed_size: Mapped[int | None] = mapped_column(BigInteger)
    last_observed_modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint_placeholder: Mapped[str | None] = mapped_column(String(255))
    is_4k: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lifecycle_state: Mapped[FileLifecycleState] = mapped_column(
        enum_type(FileLifecycleState, "file_lifecycle_state"),
        nullable=False,
        default=FileLifecycleState.DISCOVERED,
    )
    compliance_state: Mapped[ComplianceState] = mapped_column(
        enum_type(ComplianceState, "compliance_state"),
        nullable=False,
        default=ComplianceState.UNKNOWN,
    )
    is_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_processed_policy_version: Mapped[int | None] = mapped_column()
    last_processed_profile_name: Mapped[str | None] = mapped_column(String(255))

    probe_snapshots: Mapped[list["ProbeSnapshot"]] = relationship(
        back_populates="tracked_file",
        cascade="all, delete-orphan",
        order_by="ProbeSnapshot.created_at",
    )
    plan_snapshots: Mapped[list["PlanSnapshot"]] = relationship(
        back_populates="tracked_file",
        cascade="all, delete-orphan",
        order_by="PlanSnapshot.created_at",
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="tracked_file",
        cascade="all, delete-orphan",
        order_by="Job.created_at",
    )
