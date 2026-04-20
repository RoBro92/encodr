from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, generate_uuid, json_type, utcnow
from encodr_db.models.enums import AuditEventType, AuditOutcome
from encodr_db.models.types import enum_type

if TYPE_CHECKING:
    from encodr_db.models.user import User


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_event_type_created_at", "event_type", "created_at"),
        Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=generate_uuid)
    event_type: Mapped[AuditEventType] = mapped_column(
        enum_type(AuditEventType, "audit_event_type"),
        nullable=False,
    )
    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_type(AuditOutcome, "audit_outcome"),
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255))
    source_ip: Mapped[str | None] = mapped_column(String(255))
    user_agent: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(json_type())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="audit_events")
