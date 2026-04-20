from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.auth import (
    AuthenticationFailedError,
    BootstrapDisabledError,
    InactiveUserError,
    InvalidTokenError,
)
from app.core.security import PasswordHashService, TokenService
from app.schemas.auth import AuthTokenResponse
from app.services.audit import AuditService
from encodr_db.models import AuditEventType, AuditOutcome, User, UserRole
from encodr_db.repositories import RefreshTokenRepository, UserRepository


@dataclass(slots=True)
class AuthService:
    password_hasher: PasswordHashService
    token_service: TokenService
    audit_service: AuditService

    def bootstrap_admin(
        self,
        session: Session,
        *,
        request: Request,
        username: str,
        password: str,
    ) -> User:
        users = UserRepository(session)
        if users.any_users_exist():
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.BOOTSTRAP_ADMIN_BLOCKED,
                outcome=AuditOutcome.FAILURE,
                request=request,
                username=username,
                details={"reason": "users_already_exist"},
            )
            raise BootstrapDisabledError("Bootstrap admin creation is disabled once a user exists.")

        user = users.create_user(
            username=username,
            password_hash=self.password_hasher.hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
            is_bootstrap_admin=True,
        )
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.BOOTSTRAP_ADMIN_CREATED,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=user,
            details={"role": user.role.value},
        )
        return user

    def login(
        self,
        session: Session,
        *,
        request: Request,
        username: str,
        password: str,
    ) -> AuthTokenResponse:
        users = UserRepository(session)
        user = users.get_by_username(username)
        if user is None or not self.password_hasher.verify_password(password, user.password_hash):
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.LOGIN,
                outcome=AuditOutcome.FAILURE,
                request=request,
                username=username,
                details={"reason": "invalid_credentials"},
            )
            raise AuthenticationFailedError("Invalid username or password.")

        if not user.is_active:
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.LOGIN,
                outcome=AuditOutcome.FAILURE,
                request=request,
                user=user,
                details={"reason": "inactive_user"},
            )
            raise InactiveUserError("The user account is inactive.")

        users.update_last_login(user)
        response = self._issue_tokens(session, user=user, request=request)
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.LOGIN,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=user,
        )
        return response

    def logout(
        self,
        session: Session,
        *,
        request: Request,
        user: User,
    ) -> int:
        revoked_count = RefreshTokenRepository(session).revoke_all_for_user(
            user.id,
            reason="logout",
        )
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.LOGOUT,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=user,
            details={"revoked_refresh_tokens": revoked_count},
        )
        return revoked_count

    def refresh(
        self,
        session: Session,
        *,
        request: Request,
        refresh_token: str,
    ) -> AuthTokenResponse:
        refresh_tokens = RefreshTokenRepository(session)
        token_hash = self.token_service.hash_refresh_token(refresh_token)
        token_record = refresh_tokens.get_active_by_token_hash(token_hash)
        if token_record is None:
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.TOKEN_REFRESH,
                outcome=AuditOutcome.FAILURE,
                request=request,
                details={"reason": "refresh_token_invalid"},
            )
            raise InvalidTokenError("The refresh token is invalid or expired.")

        user = token_record.user
        if not user.is_active:
            refresh_tokens.revoke_token(token_record, reason="user_inactive")
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.TOKEN_REFRESH,
                outcome=AuditOutcome.FAILURE,
                request=request,
                user=user,
                details={"reason": "inactive_user"},
            )
            raise InactiveUserError("The user account is inactive.")

        refresh_tokens.mark_used(token_record)
        refresh_tokens.revoke_token(token_record, reason="rotated")
        response = self._issue_tokens(session, user=user, request=request)
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.TOKEN_REFRESH,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=user,
        )
        return response

    def _issue_tokens(
        self,
        session: Session,
        *,
        user: User,
        request: Request,
    ) -> AuthTokenResponse:
        refresh_token, refresh_expires_in = self.token_service.generate_refresh_token()
        access_token, access_expires_in = self.token_service.create_access_token(user)
        RefreshTokenRepository(session).create_token(
            user_id=user.id,
            token_hash=self.token_service.hash_refresh_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + self.token_service.settings.refresh_token_ttl,
            issued_by_ip=request.client.host if request.client is not None else None,
            issued_user_agent=request.headers.get("user-agent"),
        )
        return AuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_in=access_expires_in,
            refresh_token_expires_in=refresh_expires_in,
        )
