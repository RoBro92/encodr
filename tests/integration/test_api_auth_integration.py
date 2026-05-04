from __future__ import annotations

from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import AuditEventType, AuditOutcome, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from encodr_shared.diagnostics import read_log_events
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
    diagnostic_events = {event.event for event in _diagnostic_events(context)}
    assert "auth_bootstrap_admin_created" in diagnostic_events
    assert "auth_login_succeeded" in diagnostic_events
    assert "auth_refresh_succeeded" in diagnostic_events
    assert "auth_logout_succeeded" in diagnostic_events

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
    assert _diagnostic_events(context, "auth_login_failed")[0].fields["status"] == 403


def test_auth_diagnostics_cover_ui_visible_failures_and_admin_denial(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)
    hasher = load_api_security_module().PasswordHashService("argon2id")

    bootstrap_admin(context.client)
    blocked_bootstrap = context.client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "another", "password": "super-secure-password"},
    )
    bad_login = context.client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    bad_refresh = context.client.post("/api/auth/refresh", json={"refresh_token": "x" * 48})
    missing_auth = context.client.get("/api/auth/me")
    invalid_auth = context.client.get("/api/auth/me", headers={"Authorization": "Bearer invalid-token"})

    with session_factory() as session:
        UserRepository(session).create_user(
            username="operator",
            password_hash=hasher.hash_password("super-secure-password"),
            role=UserRole.OPERATOR,
            is_active=True,
        )
        session.commit()

    operator_auth = login_user(context.client, username="operator")
    admin_denial = context.client.get("/api/system/runtime", headers=operator_auth.headers)

    assert blocked_bootstrap.status_code == 403
    assert bad_login.status_code == 401
    assert bad_refresh.status_code == 401
    assert missing_auth.status_code == 401
    assert invalid_auth.status_code == 401
    assert admin_denial.status_code == 403

    events = {event.event: event for event in _diagnostic_events(context)}
    assert events["auth_bootstrap_admin_failed"].fields["status"] == 403
    assert events["auth_login_failed"].fields["status"] == 401
    assert events["auth_refresh_failed"].fields["status"] == 401
    assert events["auth_missing_credentials"].fields["path"] == "/api/auth/me"
    assert events["auth_invalid_credentials"].fields["reason"] == "access_token_decode_failed"
    assert events["auth_admin_access_denied"].fields["username"] == "operator"

    raw_logs = (context.bundle.app.data_dir / "logs" / "api.jsonl").read_text(encoding="utf-8")
    assert "wrong-password" not in raw_logs


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
    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.data_dir = tmp_path / "data"
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    return context, session_factory


def _diagnostic_events(context, event: str | None = None):
    return read_log_events(
        context.bundle.app.data_dir / "logs",
        component="api",
        event=event,
        limit=1000,
    )
