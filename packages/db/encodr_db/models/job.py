from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin, json_type
from encodr_db.models.enums import JobStatus, ReplacementStatus, VerificationStatus, WorkerType
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.manual_review_decision import ManualReviewDecision
    from encodr_db.models.plan_snapshot import PlanSnapshot
    from encodr_db.models.tracked_file import TrackedFile
    from encodr_db.models.worker import Worker


class Job(Base, IdMixin, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_started_at", "started_at"),
        Index("ix_jobs_completed_at", "completed_at"),
    )

    tracked_file_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("plan_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"),
        index=True,
    )
    last_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"),
        index=True,
    )
    requested_worker_type: Mapped[WorkerType | None] = mapped_column(
        enum_type(WorkerType, "worker_type"),
        index=True,
    )
    worker_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_stage: Mapped[str | None] = mapped_column(String(255))
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    progress_out_time_seconds: Mapped[int | None] = mapped_column(Integer)
    progress_fps: Mapped[float | None] = mapped_column(Float)
    progress_speed: Mapped[float | None] = mapped_column(Float)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_message: Mapped[str | None] = mapped_column(Text)
    failure_category: Mapped[str | None] = mapped_column(String(255), index=True)
    input_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    space_saved_bytes: Mapped[int | None] = mapped_column(BigInteger)
    video_input_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    video_output_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    video_space_saved_bytes: Mapped[int | None] = mapped_column(BigInteger)
    non_video_space_saved_bytes: Mapped[int | None] = mapped_column(BigInteger)
    compression_reduction_percent: Mapped[int | None] = mapped_column(Integer)
    output_path: Mapped[str | None] = mapped_column(Text)
    execution_command: Mapped[list[str] | None] = mapped_column(json_type())
    execution_stdout: Mapped[str | None] = mapped_column(Text)
    execution_stderr: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, "verification_status"),
        nullable=False,
        default=VerificationStatus.PENDING,
    )
    verification_payload: Mapped[dict | None] = mapped_column(json_type())
    replacement_status: Mapped[ReplacementStatus] = mapped_column(
        enum_type(ReplacementStatus, "replacement_status"),
        nullable=False,
        default=ReplacementStatus.PENDING,
    )
    replacement_payload: Mapped[dict | None] = mapped_column(json_type())
    final_output_path: Mapped[str | None] = mapped_column(Text)
    original_backup_path: Mapped[str | None] = mapped_column(Text)
    replacement_failure_message: Mapped[str | None] = mapped_column(Text)
    replace_in_place: Mapped[bool] = mapped_column(nullable=False, default=True)
    require_verification: Mapped[bool] = mapped_column(nullable=False, default=True)
    keep_original_until_verified: Mapped[bool] = mapped_column(nullable=False, default=True)
    delete_replaced_source: Mapped[bool] = mapped_column(nullable=False, default=False)

    tracked_file: Mapped["TrackedFile"] = relationship(back_populates="jobs")
    plan_snapshot: Mapped["PlanSnapshot"] = relationship(back_populates="jobs")
    assigned_worker: Mapped["Worker | None"] = relationship(
        back_populates="assigned_jobs",
        foreign_keys=[assigned_worker_id],
    )
    last_worker: Mapped["Worker | None"] = relationship(
        back_populates="processed_jobs",
        foreign_keys=[last_worker_id],
    )
    manual_review_decisions: Mapped[list["ManualReviewDecision"]] = relationship(back_populates="job")
