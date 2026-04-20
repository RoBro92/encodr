from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import PasswordHashService, TokenService, WorkerTokenService
from app.core.worker_auth import WorkerAuthRuntimeSettings
from encodr_core.config import ConfigBundle
from encodr_db.models import AuditEventType, AuditOutcome, User, UserRole, Worker, WorkerRegistrationStatus
from encodr_db.repositories import AuditEventRepository, UserRepository, WorkerRepository
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


def get_worker_token_service(request: Request) -> WorkerTokenService:
    return request.app.state.worker_token_service


def get_worker_auth_runtime_settings(request: Request) -> WorkerAuthRuntimeSettings:
    return request.app.state.worker_auth_runtime


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


def require_authenticated_worker(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
    worker_token_service: WorkerTokenService = Depends(get_worker_token_service),
) -> Worker:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = worker_token_service.hash_worker_token(credentials.credentials)
    worker = WorkerRepository(session).get_by_token_hash(token_hash)
    if worker is None or worker.worker_type.value != "remote":
        AuditEventRepository(session).add_event(
            event_type=AuditEventType.WORKER_HEARTBEAT_AUTH_FAILURE,
            outcome=AuditOutcome.FAILURE,
            username="unknown-worker",
            source_ip=request.client.host if request.client is not None else None,
            user_agent=request.headers.get("user-agent"),
            details={"reason": "invalid_worker_token"},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not worker.enabled or worker.registration_status != WorkerRegistrationStatus.REGISTERED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The worker is disabled or not registered.",
        )
    return worker
