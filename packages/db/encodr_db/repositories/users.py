from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from encodr_db.models import User, UserRole


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def any_users_exist(self) -> bool:
        return self.session.scalar(select(User.id).limit(1)) is not None

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: UserRole = UserRole.ADMIN,
        is_active: bool = True,
        is_bootstrap_admin: bool = False,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            is_bootstrap_admin=is_bootstrap_admin,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(User.username == username))

    def get_by_id(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def update_last_login(self, user: User) -> User:
        user.last_login_at = datetime.now(timezone.utc)
        self.session.flush()
        return user

    def list_users(self, *, limit: int | None = None) -> list[User]:
        query: Select[tuple[User]] = select(User).order_by(desc(User.created_at))
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def count_users(self) -> int:
        return int(self.session.scalar(select(func.count(User.id))) or 0)
