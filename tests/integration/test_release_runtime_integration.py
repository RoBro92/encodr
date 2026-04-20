from __future__ import annotations

from pathlib import Path

import pytest

from encodr_shared import UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import parse_version, read_version
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory

pytestmark = [pytest.mark.integration]
CURRENT_VERSION = read_version(Path(__file__))


def next_patch_version(version: str) -> str:
    parts = list(parse_version(version))
    parts[-1] += 1
    return ".".join(str(part) for part in parts)


def test_health_endpoint_exposes_current_version(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context(tmp_path, repo_root, monkeypatch)

    response = context.client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["version"] == CURRENT_VERSION


def test_bootstrap_status_reports_first_user_setup_required(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context(tmp_path, repo_root, monkeypatch)

    response = context.client.get("/api/auth/bootstrap-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bootstrap_allowed"] is True
    assert payload["first_user_setup_required"] is True
    assert payload["user_count"] == 0
    assert payload["version"] == CURRENT_VERSION


def test_update_status_endpoint_returns_current_and_latest_versions(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context(tmp_path, repo_root, monkeypatch)
    bootstrap_admin(context.client)
    auth = login_user(context.client)
    latest_version = next_patch_version(CURRENT_VERSION)
    context.app.state.update_checker = UpdateChecker(
        current_version=CURRENT_VERSION,
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: {
            "latest_version": latest_version,
            "channel": "internal",
            "download_url": f"https://downloads.example.invalid/encodr-{latest_version}.tar.gz",
            "release_notes_url": f"https://downloads.example.invalid/encodr-{latest_version}-notes",
        },
    )

    response = context.client.get("/api/system/update", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_version"] == CURRENT_VERSION
    assert payload["latest_version"] == latest_version
    assert payload["update_available"] is True


def test_update_check_endpoint_reports_upstream_error(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context(tmp_path, repo_root, monkeypatch)
    bootstrap_admin(context.client)
    auth = login_user(context.client)
    context.app.state.update_checker = UpdateChecker(
        current_version=CURRENT_VERSION,
        settings=UpdateCheckSettings(
            enabled=True,
            metadata_url="https://updates.example.invalid/encodr.json",
            channel="internal",
            timeout_seconds=2,
        ),
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(ValueError("upstream unavailable")),
    )

    response = context.client.post("/api/system/update/check", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"] == "upstream unavailable"


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'release-runtime.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    bundle = None
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    return context
