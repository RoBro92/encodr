from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from encodr_db.alembic_runtime import is_placeholder_database_url, resolve_database_url


def _bundle(database_url: str) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(database=SimpleNamespace(dsn=database_url)))


def test_container_migration_prefers_runtime_config_over_alembic_placeholder() -> None:
    configured_url = "postgresql+psycopg://encodr:change-me-before-production@localhost:5432/encodr"
    runtime_url = "postgresql+psycopg://encodr:runtime-secret@postgres:5432/encodr"

    resolved = resolve_database_url(
        configured_url,
        environ={},
        config_loader=lambda: _bundle(runtime_url),
    )

    assert resolved == runtime_url


def test_env_database_url_overrides_runtime_config() -> None:
    explicit_url = "postgresql+psycopg://encodr:explicit@postgres:5432/encodr"
    runtime_url = "postgresql+psycopg://encodr:runtime-secret@postgres:5432/encodr"

    resolved = resolve_database_url(
        "postgresql+psycopg://encodr:change-me-before-production@postgres:5432/encodr",
        environ={"ENCODR_DATABASE_URL": explicit_url},
        config_loader=lambda: _bundle(runtime_url),
    )

    assert resolved == explicit_url


def test_host_reachable_alembic_url_is_preserved_for_cli_or_admin_use() -> None:
    host_url = "postgresql+psycopg://encodr:local-secret@127.0.0.1:55432/encodr"

    resolved = resolve_database_url(
        host_url,
        environ={},
        config_loader=lambda: _bundle("postgresql+psycopg://encodr:runtime-secret@postgres:5432/encodr"),
    )

    assert resolved == host_url


def test_alembic_ini_is_container_safe_placeholder(repo_root: Path) -> None:
    alembic_ini = (repo_root / "packages" / "db" / "alembic.ini").read_text(encoding="utf-8")

    assert "@localhost:" not in alembic_ini
    assert "@127.0.0.1:" not in alembic_ini
    assert "change-me-before-production@postgres:5432/encodr" in alembic_ini
    assert is_placeholder_database_url("postgresql+psycopg://encodr:change-me-before-production@postgres:5432/encodr")
