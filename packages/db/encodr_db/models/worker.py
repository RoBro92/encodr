from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin, json_type
from encodr_db.models.enums import WorkerHealthStatus, WorkerRegistrationStatus, WorkerType
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.job import Job


class Worker(Base, IdMixin, TimestampMixin):
    __tablename__ = "workers"
    __table_args__ = (
        Index("ix_workers_worker_key", "worker_key", unique=True),
        Index("ix_workers_worker_type_enabled", "worker_type", "enabled"),
        Index("ix_workers_last_seen_at", "last_seen_at"),
    )

    worker_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_type: Mapped[WorkerType] = mapped_column(
        enum_type(WorkerType, "worker_type"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    registration_status: Mapped[WorkerRegistrationStatus] = mapped_column(
        enum_type(WorkerRegistrationStatus, "worker_registration_status"),
        nullable=False,
        default=WorkerRegistrationStatus.UNKNOWN,
    )
    auth_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    host_metadata: Mapped[dict | None] = mapped_column(json_type())
    capability_payload: Mapped[dict | None] = mapped_column(json_type())
    runtime_payload: Mapped[dict | None] = mapped_column(json_type())
    binary_payload: Mapped[dict | None] = mapped_column(json_type())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_status: Mapped[WorkerHealthStatus] = mapped_column(
        enum_type(WorkerHealthStatus, "worker_health_status"),
        nullable=False,
        default=WorkerHealthStatus.UNKNOWN,
    )
    last_health_summary: Mapped[str | None] = mapped_column(Text)
    last_registration_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assigned_jobs: Mapped[list["Job"]] = relationship(
        back_populates="assigned_worker",
        foreign_keys="Job.assigned_worker_id",
    )
    processed_jobs: Mapped[list["Job"]] = relationship(
        back_populates="last_worker",
        foreign_keys="Job.last_worker_id",
    )
