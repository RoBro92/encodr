from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import (
    AuthenticationFailedError,
    BootstrapDisabledError,
    InactiveUserError,
    InvalidTokenError,
)
from app.core.dependencies import get_password_hasher, get_session, get_token_service, require_current_user
from app.core.security import PasswordHashService, TokenService
from app.schemas.auth import (
    AuthTokenResponse,
    BootstrapAdminRequest,
    BootstrapAdminResponse,
    BootstrapStatusResponse,
    LoginRequest,
    LogoutResponse,
    RefreshRequest,
)
from app.schemas.user import CurrentUserResponse
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.diagnostics import exception_fields
from encodr_db.repositories import UserRepository
from encodr_db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("encodr.api.auth")


def get_auth_service(
    password_hasher: PasswordHashService = Depends(get_password_hasher),
    token_service: TokenService = Depends(get_token_service),
) -> AuthService:
    return AuthService(
        password_hasher=password_hasher,
        token_service=token_service,
        audit_service=AuditService(),
    )


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(
    request: Request,
    session: Session = Depends(get_session),
) -> BootstrapStatusResponse:
    user_count = UserRepository(session).count_users()
    bootstrap_allowed = user_count == 0
    return BootstrapStatusResponse(
        bootstrap_allowed=bootstrap_allowed,
        first_user_setup_required=bootstrap_allowed,
        user_count=user_count,
        version=request.app.state.app_version,
    )


@router.post("/bootstrap-admin", response_model=BootstrapAdminResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_admin(
    payload: BootstrapAdminRequest,
    request: Request,
    session: Session = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> BootstrapAdminResponse:
    try:
        user = auth_service.bootstrap_admin(
            session,
            request=request,
            username=payload.username,
            password=payload.password,
        )
        session.commit()
        logger.info(
            "bootstrap admin created",
            extra={
                "event": "auth_bootstrap_admin_created",
                "status": status.HTTP_201_CREATED,
                "user_id": user.id,
                "username": user.username,
            },
        )
        return BootstrapAdminResponse(user=CurrentUserResponse.from_user(user))
    except BootstrapDisabledError as error:
        session.commit()
        logger.warning(
            "bootstrap admin blocked",
            extra={
                "event": "auth_bootstrap_admin_failed",
                "status": status.HTTP_403_FORBIDDEN,
                "username": payload.username,
                **exception_fields(error),
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        response = auth_service.login(
            session,
            request=request,
            username=payload.username,
            password=payload.password,
        )
        session.commit()
        user = UserRepository(session).get_by_username(payload.username)
        logger.info(
            "login succeeded",
            extra={
                "event": "auth_login_succeeded",
                "status": status.HTTP_200_OK,
                "user_id": user.id if user is not None else None,
                "username": user.username if user is not None else payload.username,
            },
        )
        return response
    except AuthenticationFailedError as error:
        session.commit()
        logger.warning(
            "login failed",
            extra={
                "event": "auth_login_failed",
                "status": status.HTTP_401_UNAUTHORIZED,
                "username": payload.username,
                **exception_fields(error),
            },
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except InactiveUserError as error:
        session.commit()
        logger.warning(
            "login failed",
            extra={
                "event": "auth_login_failed",
                "status": status.HTTP_403_FORBIDDEN,
                "username": payload.username,
                **exception_fields(error),
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    current_user: User = Depends(require_current_user),
    session: Session = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    auth_service.logout(session, request=request, user=current_user)
    session.commit()
    logger.info(
        "logout succeeded",
        extra={
            "event": "auth_logout_succeeded",
            "status": status.HTTP_200_OK,
            "user_id": current_user.id,
            "username": current_user.username,
        },
    )
    return LogoutResponse()


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(
    payload: RefreshRequest,
    request: Request,
    session: Session = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        response = auth_service.refresh(
            session,
            request=request,
            refresh_token=payload.refresh_token,
        )
        session.commit()
        logger.info(
            "refresh succeeded",
            extra={
                "event": "auth_refresh_succeeded",
                "status": status.HTTP_200_OK,
            },
        )
        return response
    except InvalidTokenError as error:
        session.commit()
        logger.warning(
            "refresh failed",
            extra={
                "event": "auth_refresh_failed",
                "status": status.HTTP_401_UNAUTHORIZED,
                **exception_fields(error),
            },
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except InactiveUserError as error:
        session.commit()
        logger.warning(
            "refresh failed",
            extra={
                "event": "auth_refresh_failed",
                "status": status.HTTP_403_FORBIDDEN,
                **exception_fields(error),
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user_details(current_user: User = Depends(require_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse.from_user(current_user)
