from __future__ import annotations

from pathlib import Path

import pytest

from encodr_db.models import AuditEventType, AuditOutcome, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from tests.helpers.api import create_test_api_context, load_api_security_module
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_real_api_and_db_auth_flow_with_migrated_schema(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    bootstrap_admin(context.client)
    auth = login_user(context.client)

    me_response = context.client.get("/api/auth/me", headers=auth.headers)
    refresh_response = context.client.post(
        "/api/auth/refresh",
        json={"refresh_token": auth.refresh_token},
    )
    logout_response = context.client.post("/api/auth/logout", headers=auth.headers)

    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"
    assert refresh_response.status_code == 200
    assert logout_response.status_code == 200

    with session_factory() as session:
        event_pairs = {
            (event.event_type, event.outcome)
            for event in AuditEventRepository(session).list_events(limit=20)
        }
        assert (AuditEventType.BOOTSTRAP_ADMIN_CREATED, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.LOGIN, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.TOKEN_REFRESH, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.LOGOUT, AuditOutcome.SUCCESS) in event_pairs


def test_inactive_user_is_denied_with_real_app(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)
    hasher = load_api_security_module().PasswordHashService("argon2id")

    with session_factory() as session:
        UserRepository(session).create_user(
            username="inactive",
            password_hash=hasher.hash_password("super-secure-password"),
            role=UserRole.ADMIN,
            is_active=False,
        )
        session.commit()

    response = context.client.post(
        "/api/auth/login",
        json={"username": "inactive", "password": "super-secure-password"},
    )

    assert response.status_code == 403


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'integration-api.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
    )
    return context, session_factory
