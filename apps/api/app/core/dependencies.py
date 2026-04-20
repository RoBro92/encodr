from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import PasswordHashService, TokenService
from encodr_core.config import ConfigBundle
from encodr_db.models import User, UserRole
from encodr_db.repositories import UserRepository
from encodr_db.runtime import LocalWorkerLoop

bearer_scheme = HTTPBearer(auto_error=False)


def get_session_factory(request: Request) -> sessionmaker:
    return request.app.state.session_factory


def get_session(
    session_factory: sessionmaker = Depends(get_session_factory),
) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_password_hasher(request: Request) -> PasswordHashService:
    return request.app.state.password_hasher


def get_token_service(request: Request) -> TokenService:
    return request.app.state.token_service


def get_config_bundle(request: Request) -> ConfigBundle:
    return request.app.state.config_bundle


def get_local_worker_loop(request: Request) -> LocalWorkerLoop:
    return request.app.state.local_worker_loop


def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
    token_service: TokenService = Depends(get_token_service),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = token_service.decode_access_token(credentials.credentials)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    user = UserRepository(session).get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin_user(current_user: User = Depends(require_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required.",
        )
    return current_user
