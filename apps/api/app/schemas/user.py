from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from encodr_db.models import User


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str
    is_active: bool
    is_bootstrap_admin: bool
    last_login_at: datetime | None = None

    @classmethod
    def from_user(cls, user: User) -> "CurrentUserResponse":
        return cls(
            id=user.id,
            username=user.username,
            role=user.role.value,
            is_active=user.is_active,
            is_bootstrap_admin=user.is_bootstrap_admin,
            last_login_at=user.last_login_at,
        )
