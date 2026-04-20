from __future__ import annotations

from pathlib import Path

import pytest

from app.executor.loop import LocalWorkerLoop
from app.executor.service import WorkerExecutionService
from encodr_core.config import load_config_bundle
from encodr_core.verification import OutputVerifier
from encodr_db.models import Job
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import StaticProbeClient, StagedRunner, create_job, media_at_path, parse_fixture

pytestmark = [pytest.mark.e2e, pytest.mark.smoke, pytest.mark.security]


def test_local_stack_vertical_slice(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'local-stack.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")

    api_context = create_test_api_context(repo_root=repo_root, session_factory=session_factory)
    unauthenticated = api_context.client.get("/api/health/authenticated")
    assert unauthenticated.status_code == 401

    bootstrap_admin(api_context.client)
    auth = login_user(api_context.client)
    authenticated = api_context.client.get("/api/health/authenticated", headers=auth.headers)
    assert authenticated.status_code == 200

    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    source_path = layout.create_source_file("Movies/Example Remux Film (2024).mkv", contents="original")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)

    with session_factory() as session:
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    loop = LocalWorkerLoop(
        session_factory,
        bundle,
        execution_service=WorkerExecutionService(
            runner=StagedRunner(output_path=layout.scratch_dir / "e2e-output.mkv"),
            verifier=OutputVerifier(probe_client=StaticProbeClient(media)),
        ),
        poll_interval_seconds=0.01,
    )

    assert loop.run_once() is True
    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status.value == "completed"
        assert job.final_output_path == source_path.as_posix()
        assert job.tracked_file.source_path == source_path.as_posix()
    assert source_path.read_text(encoding="utf-8") == "staged output"
