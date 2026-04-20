from __future__ import annotations

from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import AuditEventType, AuditOutcome
from encodr_db.repositories import AuditEventRepository, WorkerRepository
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_worker_registration_succeeds_with_valid_bootstrap_secret(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    response = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))

    assert response.status_code == 201
    payload = response.json()
    assert payload["worker_key"] == "remote-amd-01"
    assert payload["worker_type"] == "remote"
    assert payload["worker_token"]

    with session_factory() as session:
        worker = WorkerRepository(session).get_by_key("remote-amd-01")
        assert worker is not None
        assert worker.auth_token_hash != payload["worker_token"]
        assert worker.last_health_status.value == "healthy"


def test_worker_registration_fails_with_invalid_secret(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    response = context.client.post("/api/worker/register", json=registration_payload("wrong-secret"))

    assert response.status_code == 401

    with session_factory() as session:
        events = AuditEventRepository(session).list_events(limit=10)
        assert any(
            event.event_type == AuditEventType.WORKER_REGISTRATION and event.outcome == AuditOutcome.FAILURE
            for event in events
        )


def test_worker_heartbeat_succeeds_with_valid_worker_token(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)
    registration = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))
    worker_token = registration.json()["worker_token"]

    response = context.client.post(
        "/api/worker/heartbeat",
        json={
            "health_status": "degraded",
            "health_summary": "GPU queue is warming up.",
            "runtime_summary": {"queue": "remote-amd", "scratch_dir": "/srv/scratch", "media_mounts": ["/srv/media"], "last_completed_job_id": None},
        },
        headers={"Authorization": f"Bearer {worker_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["worker_key"] == "remote-amd-01"
    assert payload["health_status"] == "degraded"

    with session_factory() as session:
        worker = WorkerRepository(session).get_by_key("remote-amd-01")
        assert worker is not None
        assert worker.last_health_status.value == "degraded"
        assert worker.runtime_payload["queue"] == "remote-amd"


def test_worker_heartbeat_fails_with_invalid_token_and_is_audited(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    response = context.client.post(
        "/api/worker/heartbeat",
        json={"health_status": "healthy", "health_summary": "ok"},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    with session_factory() as session:
        events = AuditEventRepository(session).list_events(limit=10)
        assert any(
            event.event_type == AuditEventType.WORKER_HEARTBEAT_AUTH_FAILURE
            and event.outcome == AuditOutcome.FAILURE
            for event in events
        )


def test_admin_worker_list_and_detail_show_local_and_remote_workers(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    registration = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))
    remote_id = registration.json()["worker_id"]

    list_response = context.client.get("/api/workers", headers=auth.headers)
    detail_response = context.client.get(f"/api/workers/{remote_id}", headers=auth.headers)
    local_response = context.client.get("/api/workers/worker-local", headers=auth.headers)

    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["worker_type"] == "local" for item in items)
    assert any(item["worker_type"] == "remote" for item in items)
    assert detail_response.status_code == 200
    assert detail_response.json()["worker_type"] == "remote"
    assert local_response.status_code == 200
    assert local_response.json()["worker_type"] == "local"


def test_admin_worker_endpoints_require_user_auth(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/workers").status_code == 401
    assert context.client.get("/api/workers/worker-local").status_code == 401
    assert context.client.post("/api/workers/worker-local/disable").status_code == 401


def test_remote_worker_enable_disable_flow_is_audited(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    registration = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))
    remote_id = registration.json()["worker_id"]
    worker_token = registration.json()["worker_token"]

    disable_response = context.client.post(f"/api/workers/{remote_id}/disable", headers=auth.headers)
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "disabled"

    blocked_heartbeat = context.client.post(
        "/api/worker/heartbeat",
        json={"health_status": "healthy", "health_summary": "ok"},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert blocked_heartbeat.status_code == 403

    enable_response = context.client.post(f"/api/workers/{remote_id}/enable", headers=auth.headers)
    assert enable_response.status_code == 200
    assert enable_response.json()["status"] == "enabled"

    with session_factory() as session:
        events = AuditEventRepository(session).list_events(limit=20)
        assert any(event.event_type == AuditEventType.WORKER_STATE_CHANGE for event in events)


def registration_payload(secret: str) -> dict:
    return {
        "registration_secret": secret,
        "worker_key": "remote-amd-01",
        "display_name": "Remote AMD Worker",
        "worker_type": "remote",
        "capability_summary": {
            "execution_modes": ["remux", "transcode"],
            "supported_video_codecs": ["hevc"],
            "supported_audio_codecs": [],
            "hardware_hints": ["amd_gpu"],
            "binary_support": {"ffmpeg": True, "ffprobe": True},
            "max_concurrent_jobs": 1,
            "tags": ["remote", "amd"],
        },
        "host_summary": {
            "hostname": "worker-amd",
            "platform": "Linux",
            "agent_version": "0.1.0",
            "python_version": "3.12",
        },
        "runtime_summary": {
            "queue": "remote-amd",
            "scratch_dir": "/srv/scratch",
            "media_mounts": ["/srv/media"],
            "last_completed_job_id": None,
        },
        "binary_summary": [
            {"name": "ffmpeg", "configured_path": "/usr/bin/ffmpeg", "discoverable": True, "message": "OK"},
            {"name": "ffprobe", "configured_path": "/usr/bin/ffprobe", "discoverable": True, "message": "OK"},
        ],
        "health_status": "healthy",
        "health_summary": "Ready for future remote dispatch groundwork.",
    }


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'worker-registration.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )

    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    bundle.workers.local.media_mounts = [layout.source_dir]

    ffmpeg_path = create_fake_binary(tmp_path / "bin" / "ffmpeg")
    ffprobe_path = create_fake_binary(tmp_path / "bin" / "ffprobe")
    bundle.app.media.ffmpeg_path = ffmpeg_path
    bundle.app.media.ffprobe_path = ffprobe_path

    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    monkeypatch.setenv("ENCODR_WORKER_REGISTRATION_SECRET", "valid-secret")
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    return context, session_factory


def authenticate(context) -> object:
    bootstrap_admin(context.client)
    return login_user(context.client)


def create_fake_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path
