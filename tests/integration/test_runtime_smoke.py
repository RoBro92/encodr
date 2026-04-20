from __future__ import annotations

from pathlib import Path

import pytest

from app.executor.loop import LocalWorkerLoop
from encodr_core.config import load_config_bundle
from tests.helpers.api import create_test_api_context
from tests.helpers.db import create_migrated_session_factory

pytestmark = [pytest.mark.integration, pytest.mark.smoke]


def test_config_bundle_loads(repo_root: Path) -> None:
    bundle = load_config_bundle(project_root=repo_root)
    assert bundle.app.name == "encodr"


def test_database_can_migrate_and_app_can_boot(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'smoke.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")

    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
    )

    assert context.client.get("/api/health").status_code == 200


def test_worker_loop_boots_with_real_bundle_and_session_factory(tmp_path: Path, repo_root: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'worker-smoke.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
    bundle = load_config_bundle(project_root=repo_root)

    loop = LocalWorkerLoop(session_factory, bundle, poll_interval_seconds=0.01)

    assert loop.run_once() is False
