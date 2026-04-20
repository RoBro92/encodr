from __future__ import annotations

from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_core.config.base import EnvironmentName
from encodr_db.repositories import RefreshTokenRepository, UserRepository
from tests.helpers.api import (
    create_test_api_context,
    load_api_auth_module,
    load_api_security_module,
    load_api_worker_auth_module,
)
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory, list_table_names

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_migrations_produce_expected_auth_schema(tmp_path: Path, repo_root: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'security-schema.sqlite').as_posix()}"
    engine, _ = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)

    table_names = list_table_names(engine)

    assert "users" in table_names
    assert "refresh_tokens" in table_names
    assert "audit_events" in table_names
    assert "tracked_files" in table_names


def test_protected_routes_reject_missing_and_invalid_tokens(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _ = build_context(tmp_path, repo_root, monkeypatch)
    bootstrap_admin(context.client)

    missing = context.client.get("/api/auth/me")
    invalid = context.client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_refresh_tokens_and_passwords_are_not_persisted_in_plain_form(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)
    bootstrap_admin(context.client)
    auth = login_user(context.client)

    with session_factory() as session:
        user = UserRepository(session).get_by_username("admin")
        refresh_tokens = RefreshTokenRepository(session).list_tokens_for_user(user.id)
        assert user is not None
        assert user.password_hash != "super-secure-password"
        assert refresh_tokens[0].token_hash != auth.refresh_token


def test_missing_auth_secret_is_rejected_in_production(tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = load_api_auth_module()
    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.environment = EnvironmentName.PRODUCTION
    monkeypatch.delenv("ENCODR_AUTH_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="ENCODR_AUTH_SECRET"):
        auth_module.load_auth_runtime_settings(bundle.app)


def test_development_auth_secret_fallback_is_available(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = load_api_auth_module()
    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.environment = EnvironmentName.TESTING
    monkeypatch.delenv("ENCODR_AUTH_SECRET", raising=False)

    settings = auth_module.load_auth_runtime_settings(bundle.app)

    assert settings.secret_key
    assert len(settings.secret_key) >= 32


def test_missing_worker_registration_secret_is_rejected_in_production(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_auth_module = load_api_worker_auth_module()
    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.environment = EnvironmentName.PRODUCTION
    monkeypatch.delenv("ENCODR_WORKER_REGISTRATION_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="ENCODR_WORKER_REGISTRATION_SECRET"):
        worker_auth_module.load_worker_auth_runtime_settings(bundle.app)


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'security.sqlite').as_posix()}"
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
