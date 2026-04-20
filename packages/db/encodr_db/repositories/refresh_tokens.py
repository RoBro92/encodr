from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from encodr_db.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        issued_by_ip: str | None = None,
        issued_user_agent: str | None = None,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            issued_by_ip=issued_by_ip,
            issued_user_agent=issued_user_agent,
        )
        self.session.add(token)
        self.session.flush()
        return token

    def get_active_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        now = datetime.now(timezone.utc)
        return self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
        )

    def revoke_token(self, token: RefreshToken, *, reason: str) -> RefreshToken:
        token.revoked_at = datetime.now(timezone.utc)
        token.revocation_reason = reason
        self.session.flush()
        return token

    def revoke_all_for_user(self, user_id: str, *, reason: str) -> int:
        now = datetime.now(timezone.utc)
        active_tokens = list(
            self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > now,
                )
            )
        )
        for token in active_tokens:
            token.revoked_at = now
            token.revocation_reason = reason
        self.session.flush()
        return len(active_tokens)

    def mark_used(self, token: RefreshToken) -> RefreshToken:
        token.last_used_at = datetime.now(timezone.utc)
        self.session.flush()
        return token

    def list_tokens_for_user(self, user_id: str) -> list[RefreshToken]:
        query: Select[tuple[RefreshToken]] = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(desc(RefreshToken.created_at))
        )
        return list(self.session.scalars(query))
