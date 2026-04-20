from __future__ import annotations

import json
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import FileLifecycleState, Job, JobStatus, PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.runtime import WorkerExecutionService
from encodr_core.verification import OutputVerifier
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import FilesystemLayout, create_filesystem_layout
from tests.helpers.jobs import StaticProbeClient, StagedRunner, create_job, media_at_path, parse_fixture

pytestmark = [pytest.mark.integration]


def test_authenticated_file_list_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Listed Film (2024).mkv", contents="listed")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    response = context.client.get(
        "/api/files",
        params={"lifecycle_state": FileLifecycleState.QUEUED.value, "path_search": "Listed Film"},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["source_filename"] == "Listed Film (2024).mkv"
    assert payload["items"][0]["lifecycle_state"] == FileLifecycleState.QUEUED.value


def test_new_endpoints_reject_unauthenticated_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/files").status_code == 401
    assert context.client.get("/api/jobs").status_code == 401
    assert context.client.get("/api/config/effective").status_code == 401
    assert context.client.post("/api/files/probe", json={"source_path": "/tmp/example.mkv"}).status_code == 401


def test_probe_endpoint_persists_tracked_file_and_probe_snapshot(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Probe Film (2024).mkv", contents="probe")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    response = context.client.post(
        "/api/files/probe",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracked_file"]["source_path"] == source_path.as_posix()
    assert payload["latest_probe_snapshot"]["file_name"] == source_path.name

    with session_factory() as session:
        assert session.query(TrackedFile).count() == 1
        assert session.query(ProbeSnapshot).count() == 1


def test_plan_endpoint_persists_plan_snapshot_and_updates_file_state(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("TV/Example Show/Season 01/Example S01E01.mkv", contents="plan")
    media = media_at_path(parse_fixture("tv_episode.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    response = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    file_id = payload["tracked_file"]["id"]
    assert payload["latest_plan_snapshot"]["action"] == "skip"

    probe_response = context.client.get(
        f"/api/files/{file_id}/probe-snapshots/latest",
        headers=auth.headers,
    )
    plan_response = context.client.get(
        f"/api/files/{file_id}/plan-snapshots/latest",
        headers=auth.headers,
    )
    assert probe_response.status_code == 200
    assert plan_response.status_code == 200

    with session_factory() as session:
        tracked_file = session.get(TrackedFile, file_id)
        assert tracked_file is not None
        assert tracked_file.lifecycle_state == FileLifecycleState.PLANNED
        assert session.query(PlanSnapshot).count() == 1


def test_job_creation_from_latest_plan_works(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Job Film (2024).mkv", contents="job")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)
    plan_response = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )
    file_id = plan_response.json()["tracked_file"]["id"]

    response = context.client.post(
        "/api/jobs",
        json={"tracked_file_id": file_id},
        headers=auth.headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == JobStatus.PENDING.value
    assert payload["tracked_file_id"] == file_id

    list_response = context.client.get("/api/jobs", headers=auth.headers)
    detail_response = context.client.get(f"/api/jobs/{payload['id']}", headers=auth.headers)
    assert list_response.status_code == 200
    assert detail_response.status_code == 200

    with session_factory() as session:
        assert session.query(Job).count() == 1


def test_retry_endpoint_creates_new_job_record(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Retry Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        session.commit()

    response = context.client.post(
        f"/api/jobs/{persisted.job.id}/retry",
        headers=auth.headers,
    )

    assert response.status_code == 201
    new_job = response.json()
    assert new_job["id"] != persisted.job.id
    assert new_job["status"] == JobStatus.PENDING.value
    assert new_job["attempt_count"] == 2

    with session_factory() as session:
        jobs = session.query(Job).order_by(Job.created_at.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].status == JobStatus.FAILED
        assert jobs[1].status == JobStatus.PENDING


def test_worker_run_once_endpoint_processes_pending_job(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Worker Film (2024).mkv", contents="original")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    context.app.state.local_worker_loop.execution_service = WorkerExecutionService(
        runner=StagedRunner(output_path=layout.scratch_dir / "api-run-once.mkv"),
        verifier=OutputVerifier(probe_client=StaticProbeClient(media)),
    )

    response = context.client.post("/api/worker/run-once", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_job"] is True
    assert payload["final_status"] == "completed"

    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status == JobStatus.COMPLETED
    assert source_path.read_text(encoding="utf-8") == "staged output"


def test_config_effective_endpoint_returns_sanitised_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    response = context.client.get("/api/config/effective", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    payload_text = json.dumps(payload).lower()
    assert payload["policy_version"] >= 1
    assert "profile_names" in payload
    assert "dsn" not in payload_text
    assert "password_hash" not in payload_text
    assert "refresh_token_hash" not in payload_text
    assert "secret_key" not in payload_text
    assert "test-auth-secret-with-sufficient-length" not in payload_text


def test_system_and_worker_status_endpoints_return_useful_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    storage_response = context.client.get("/api/system/storage", headers=auth.headers)
    runtime_response = context.client.get("/api/system/runtime", headers=auth.headers)
    worker_response = context.client.get("/api/worker/status", headers=auth.headers)

    assert storage_response.status_code == 200
    assert runtime_response.status_code == 200
    assert worker_response.status_code == 200
    assert storage_response.json()["scratch"]["path"] == layout.scratch_dir.as_posix()
    assert runtime_response.json()["db_reachable"] is True
    assert worker_response.json()["worker_name"] == "worker-local"
    assert worker_response.json()["local_only"] is True


def test_invalid_source_path_handling_is_clear_and_safe(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    response = context.client.post(
        "/api/files/probe",
        json={"source_path": (tmp_path / "missing-file.mkv").as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'api-ops.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )

    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    bundle.app.data_dir = layout.root / "data"
    bundle.workers.local.media_mounts = [layout.source_dir]

    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    return context, session_factory, layout, bundle


def authenticate(context) -> object:
    bootstrap_admin(context.client)
    return login_user(context.client)
