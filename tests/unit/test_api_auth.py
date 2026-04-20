from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import sessionmaker

from encodr_db.models import AuditEventType, AuditOutcome, UserRole
from encodr_db.repositories import AuditEventRepository, UserRepository
from tests.helpers.api import create_test_api_context, load_api_security_module
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_schema_session_factory

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_admin_works_only_when_no_users_exist(monkeypatch) -> None:
    client, session_factory = build_test_client(monkeypatch)

    response = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "super-secure-password"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["role"] == "admin"

    with session_factory() as session:
        users = UserRepository(session).list_users()
        assert len(users) == 1
        assert users[0].is_bootstrap_admin is True


def test_bootstrap_admin_is_blocked_after_first_user_exists(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)

    first = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "super-secure-password"},
    )
    second = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "another", "password": "super-secure-password"},
    )

    assert first.status_code == 201
    assert second.status_code == 403


def test_password_hashing_and_verification() -> None:
    service = load_api_security_module().PasswordHashService("argon2id")
    password_hash = service.hash_password("super-secure-password")

    assert password_hash != "super-secure-password"
    assert service.verify_password("super-secure-password", password_hash) is True
    assert service.verify_password("wrong-password", password_hash) is False


def test_successful_login_returns_valid_auth_material(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)
    bootstrap_admin(client)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "super-secure-password"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["access_token_expires_in"] > 0
    assert payload["refresh_token_expires_in"] > 0


def test_failed_login_is_rejected_and_audited(monkeypatch) -> None:
    client, session_factory = build_test_client(monkeypatch)
    bootstrap_admin(client)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )

    assert response.status_code == 401
    with session_factory() as session:
        events = AuditEventRepository(session).list_events(limit=5)
        assert any(
            event.event_type == AuditEventType.LOGIN and event.outcome == AuditOutcome.FAILURE
            for event in events
        )


def test_protected_endpoint_rejects_unauthenticated_access(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)

    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_protected_endpoint_accepts_authenticated_access(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)
    auth = login_admin(client)

    response = client.get(
        "/api/health/authenticated",
        headers=auth.headers,
    )

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_invalidates_refresh_flow(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)
    auth = login_admin(client)

    logout_response = client.post(
        "/api/auth/logout",
        headers=auth.headers,
    )
    refresh_response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": auth.refresh_token},
    )

    assert logout_response.status_code == 200
    assert refresh_response.status_code == 401


def test_refresh_works_and_rotates_refresh_token(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)
    auth = login_admin(client)

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": auth.refresh_token},
    )
    second_refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": auth.refresh_token},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_token"] != auth.refresh_token
    assert second_refresh.status_code == 401


def test_auth_me_returns_current_user_details(monkeypatch) -> None:
    client, _ = build_test_client(monkeypatch)
    auth = login_admin(client)

    response = client.get(
        "/api/auth/me",
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "admin"
    assert payload["is_bootstrap_admin"] is True


def test_inactive_users_cannot_authenticate(monkeypatch) -> None:
    client, session_factory = build_test_client(monkeypatch)
    hasher = load_api_security_module().PasswordHashService("argon2id")

    with session_factory() as session:
        UserRepository(session).create_user(
            username="inactive",
            password_hash=hasher.hash_password("super-secure-password"),
            role=UserRole.ADMIN,
            is_active=False,
        )
        session.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": "inactive", "password": "super-secure-password"},
    )

    assert response.status_code == 403


def test_audit_events_are_persisted_for_success_and_failure_cases(monkeypatch) -> None:
    client, session_factory = build_test_client(monkeypatch)
    bootstrap_admin(client)
    auth = login_admin(client)
    client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    client.post("/api/auth/refresh", json={"refresh_token": auth.refresh_token})
    client.post(
        "/api/auth/logout",
        headers=auth.headers,
    )

    with session_factory() as session:
        events = AuditEventRepository(session).list_events(limit=20)
        event_pairs = {(event.event_type, event.outcome) for event in events}
        assert (AuditEventType.BOOTSTRAP_ADMIN_CREATED, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.LOGIN, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.LOGIN, AuditOutcome.FAILURE) in event_pairs
        assert (AuditEventType.TOKEN_REFRESH, AuditOutcome.SUCCESS) in event_pairs
        assert (AuditEventType.LOGOUT, AuditOutcome.SUCCESS) in event_pairs


def build_test_client(monkeypatch) -> tuple[object, sessionmaker]:
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    _, session_factory = create_schema_session_factory()
    context = create_test_api_context(
        repo_root=REPO_ROOT,
        session_factory=session_factory,
    )
    return context.client, session_factory


def login_admin(client):
    try:
        bootstrap_admin(client)
    except AssertionError:
        pass
    return login_user(client)
