from __future__ import annotations

from pathlib import Path

import pytest

from app.executor.loop import LocalWorkerLoop
from app.executor.service import WorkerExecutionService
from encodr_core.config import load_config_bundle
from encodr_core.verification import OutputVerifier
from encodr_db.models import ComplianceState, FileLifecycleState, Job, JobStatus
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import (
    StaticProbeClient,
    StaticVerifier,
    StagedRunner,
    create_job,
    media_at_path,
    parse_fixture,
)

pytestmark = [pytest.mark.integration]


def test_worker_job_flow_completes_with_real_db_and_replacement(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'worker-flow.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
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
            runner=StagedRunner(output_path=layout.scratch_dir / "completed.mkv"),
            verifier=OutputVerifier(probe_client=StaticProbeClient(media)),
        ),
        poll_interval_seconds=0.01,
    )

    assert loop.run_once() is True
    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status == JobStatus.COMPLETED
        assert job.final_output_path == source_path.as_posix()
        assert job.tracked_file.lifecycle_state == FileLifecycleState.COMPLETED
        assert job.tracked_file.compliance_state == ComplianceState.COMPLIANT
        assert source_path.read_text(encoding="utf-8") == "staged output"


def test_worker_job_flow_fails_on_verification_and_preserves_original(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'worker-fail.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(repo_root=repo_root, database_url=database_url)
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
            runner=StagedRunner(output_path=layout.scratch_dir / "failed.mkv"),
            verifier=StaticVerifier.failed("Output verification failed."),
        ),
        poll_interval_seconds=0.01,
    )

    assert loop.run_once() is True
    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status == JobStatus.FAILED
        assert job.tracked_file.lifecycle_state == FileLifecycleState.FAILED
    assert source_path.read_text(encoding="utf-8") == "original"
