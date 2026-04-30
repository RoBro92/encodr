from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from encodr_core.config import load_config_bundle

DATABASE_URL_ENV = "ENCODR_DATABASE_URL"

_PLACEHOLDER_USERNAME = "encodr"
_PLACEHOLDER_PASSWORD = "change-me-before-production"
_PLACEHOLDER_DATABASE = "encodr"


def is_placeholder_database_url(database_url: str | None) -> bool:
    """Return true for the shipped alembic.ini example URL.

    Runtime migrations should prefer ENCODR_DATABASE_URL or the loaded app
    configuration over this example because generated installs have unique
    database credentials and container-safe hostnames.
    """
    if not database_url or not database_url.strip():
        return True

    try:
        parsed = make_url(database_url.strip())
    except ArgumentError:
        return False

    database = (parsed.database or "").lstrip("/")
    return (
        (parsed.username or "") == _PLACEHOLDER_USERNAME
        and (parsed.password or "") == _PLACEHOLDER_PASSWORD
        and database == _PLACEHOLDER_DATABASE
    )


def resolve_database_url(
    configured_url: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    config_loader: Callable[[], Any] | None = load_config_bundle,
) -> str:
    """Resolve the database URL Alembic should use at runtime.

    Precedence is:
    1. ENCODR_DATABASE_URL, for explicit one-off runtime overrides.
    2. A non-placeholder Alembic URL, for tests and intentional host CLI use.
    3. The normal Encodr app runtime config, used by Docker Compose containers.
    4. The configured Alembic placeholder as a last-resort error surface.
    """
    values = os.environ if environ is None else environ
    explicit_url = _normalise_url(values.get(DATABASE_URL_ENV))
    if explicit_url:
        return explicit_url

    configured = _normalise_url(configured_url)
    if configured and not is_placeholder_database_url(configured):
        return configured

    runtime_url = _load_runtime_config_database_url(config_loader)
    if runtime_url:
        return runtime_url

    if configured:
        return configured

    raise RuntimeError("No database URL is configured for Alembic migrations.")


def _load_runtime_config_database_url(config_loader: Callable[[], Any] | None) -> str | None:
    if config_loader is None:
        return None

    try:
        bundle = config_loader()
    except Exception:
        return None

    return _normalise_url(str(bundle.app.database.dsn))


def _normalise_url(database_url: str | None) -> str | None:
    if database_url is None:
        return None
    value = database_url.strip()
    return value or None
