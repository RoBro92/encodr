from __future__ import annotations

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
    LoginRequest,
    LogoutResponse,
    RefreshRequest,
)
from app.schemas.user import CurrentUserResponse
from app.services.audit import AuditService
from app.services.auth import AuthService
from encodr_db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(
    password_hasher: PasswordHashService = Depends(get_password_hasher),
    token_service: TokenService = Depends(get_token_service),
) -> AuthService:
    return AuthService(
        password_hasher=password_hasher,
        token_service=token_service,
        audit_service=AuditService(),
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
        return BootstrapAdminResponse(user=CurrentUserResponse.from_user(user))
    except BootstrapDisabledError as error:
        session.commit()
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
        return response
    except AuthenticationFailedError as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except InactiveUserError as error:
        session.commit()
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
        return response
    except InvalidTokenError as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except InactiveUserError as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user_details(current_user: User = Depends(require_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse.from_user(current_user)
