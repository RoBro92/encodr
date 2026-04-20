from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from encodr_db.models.base import Base, IdMixin, TimestampMixin
from encodr_db.models.types import enum_type
from encodr_db.models.enums import UserRole

if TYPE_CHECKING:
    from encodr_db.models.audit_event import AuditEvent
    from encodr_db.models.manual_review_decision import ManualReviewDecision
    from encodr_db.models.refresh_token import RefreshToken


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username", "username"),
    )

    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_type(UserRole, "user_role"),
        nullable=False,
        default=UserRole.ADMIN,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_bootstrap_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="RefreshToken.created_at",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="user",
        order_by="AuditEvent.created_at",
    )
    manual_review_decisions: Mapped[list["ManualReviewDecision"]] = relationship(
        back_populates="created_by_user",
        order_by="ManualReviewDecision.created_at",
    )
