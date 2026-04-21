from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest

from encodr_core.execution import ExecutionResult
from encodr_core.config import load_config_bundle
from encodr_db.models import AuditEventType, AuditOutcome, Job, JobStatus
from encodr_db.repositories import AuditEventRepository, WorkerRepository
from encodr_shared.versioning import read_version
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import create_job, media_at_path, parse_fixture

import sys
import importlib

WORKER_AGENT_ROOT = Path(__file__).resolve().parents[2] / "apps" / "worker-agent"
sys.modules.pop("app", None)
sys.path.insert(0, str(WORKER_AGENT_ROOT))
WorkerApiClient = importlib.import_module("app.client").WorkerApiClient  # type: ignore[attr-defined]
load_settings = importlib.import_module("app.config").load_settings  # type: ignore[attr-defined]
WorkerAgentService = importlib.import_module("app.service").WorkerAgentService  # type: ignore[attr-defined]
sys.path.remove(str(WORKER_AGENT_ROOT))
for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
    sys.modules.pop(module_name, None)

pytestmark = [pytest.mark.integration, pytest.mark.security]
CURRENT_VERSION = read_version(Path(__file__))


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


def test_remote_worker_can_request_claim_and_submit_job_result(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    source_path = context.bundle.workers.local.media_mounts[0] / "Movies" / "Remote Example.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("original", encoding="utf-8")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)

    with session_factory() as session:
        create_job(
            session,
            context.bundle,
            media,
            source_path=source_path.as_posix(),
        )
        session.commit()

    registration = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))
    worker_token = registration.json()["worker_token"]

    request_response = context.client.post(
        "/api/worker/jobs/request",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert request_response.status_code == 200
    request_payload = request_response.json()
    assert request_payload["status"] == "assigned"
    job_id = request_payload["job"]["job_id"]

    claim_response = context.client.post(
        f"/api/worker/jobs/{job_id}/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["status"] == "claimed"

    result = ExecutionResult(
        mode="remux",
        status="completed",
        command=["ffmpeg", "-i", source_path.as_posix(), source_path.as_posix()],
        output_path=source_path,
        final_output_path=source_path,
        original_backup_path=source_path.with_suffix(".encodr-backup.mkv"),
        output_size_bytes=123,
        exit_code=0,
        stdout="ok",
        stderr="",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    result_response = context.client.post(
        f"/api/worker/jobs/{job_id}/result",
        json={
            "result_payload": result.model_dump(mode="json"),
            "runtime_summary": {
                "queue": "remote-amd",
                "scratch_dir": "/srv/scratch",
                "media_mounts": ["/srv/media"],
                "last_completed_job_id": job_id,
            },
        },
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert result_response.status_code == 200
    assert result_response.json()["final_status"] == "completed"

    with session_factory() as session:
        worker = WorkerRepository(session).get_by_key("remote-amd-01")
        assert worker is not None
        assert worker.runtime_payload["last_completed_job_id"] == job_id

        from encodr_db.models import Job

        saved_job = session.get(Job, job_id)
        assert saved_job is not None
        assert saved_job.status == JobStatus.COMPLETED
        assert saved_job.last_worker_id == worker.id


def test_remote_worker_can_report_failure_for_running_job(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    source_path = context.bundle.workers.local.media_mounts[0] / "Movies" / "Remote Failure Example.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("original", encoding="utf-8")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)

    with session_factory() as session:
        create_job(
            session,
            context.bundle,
            media,
            source_path=source_path.as_posix(),
        )
        session.commit()

    registration = context.client.post("/api/worker/register", json=registration_payload("valid-secret"))
    worker_token = registration.json()["worker_token"]

    request_response = context.client.post(
        "/api/worker/jobs/request",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    job_id = request_response.json()["job"]["job_id"]
    claim_response = context.client.post(
        f"/api/worker/jobs/{job_id}/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert claim_response.status_code == 200

    failure_response = context.client.post(
        f"/api/worker/jobs/{job_id}/failure",
        json={
            "failure_message": "submit failed",
            "failure_category": "worker_agent_error",
            "runtime_summary": {
                "queue": "remote-amd",
                "scratch_dir": "/srv/scratch",
                "media_mounts": ["/srv/media"],
                "last_completed_job_id": None,
            },
        },
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert failure_response.status_code == 200
    assert failure_response.json()["final_status"] == "failed"

    with session_factory() as session:
        worker = WorkerRepository(session).get_by_key("remote-amd-01")
        assert worker is not None
        saved_job = session.get(Job, job_id)
        assert saved_job is not None
        assert saved_job.status == JobStatus.FAILED
        assert saved_job.last_worker_id == worker.id


def test_worker_agent_service_can_execute_remote_job_against_api_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TestClientRequester:
        def __init__(self, client) -> None:
            self.client = client

        def request_json(self, *, method: str, url: str, body: dict | None = None, bearer_token: str | None = None) -> dict:
            path = "/" + url.split("/api/", 1)[1]
            headers = {}
            if bearer_token is not None:
                headers["Authorization"] = f"Bearer {bearer_token}"
            response = self.client.request(method, f"/api{path}", json=body, headers=headers)
            assert response.status_code < 400, response.text
            return response.json()

    class FakeExecutionService:
        def execute(self, *, job_id: str, plan_payload: dict, media_payload: dict) -> ExecutionResult:
            del plan_payload, media_payload
            return ExecutionResult(
                mode="remux",
                status="completed",
                command=["ffmpeg", "-i", "input.mkv", "output.mkv"],
                output_path=Path("/media/output.mkv"),
                final_output_path=Path("/media/output.mkv"),
                original_backup_path=Path("/media/output.encodr-backup.mkv"),
                output_size_bytes=123,
                exit_code=0,
                stdout="ok",
                stderr="",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

    context, session_factory = build_context(tmp_path, repo_root, monkeypatch)

    source_path = context.bundle.workers.local.media_mounts[0] / "Movies" / "Remote Agent Example.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("original", encoding="utf-8")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)

    with session_factory() as session:
        create_job(
            session,
            context.bundle,
            media,
            source_path=source_path.as_posix(),
        )
        session.commit()

    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        binary = tmp_path / "bin" / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-agent-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote Agent Worker",
            "ENCODR_WORKER_AGENT_REGISTRATION_SECRET": "valid-secret",
            "ENCODR_WORKER_AGENT_QUEUE": "remote-default",
            "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(tmp_path / "scratch"),
            "ENCODR_WORKER_AGENT_MEDIA_MOUNTS": context.bundle.workers.local.media_mounts[0].as_posix(),
            "ENCODR_WORKER_AGENT_TOKEN_FILE": str(tmp_path / "worker.token"),
            "ENCODR_WORKER_AGENT_FFMPEG_PATH": str(tmp_path / "bin" / "ffmpeg"),
            "ENCODR_WORKER_AGENT_FFPROBE_PATH": str(tmp_path / "bin" / "ffprobe"),
        }
    )
    requester = TestClientRequester(context.client)
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    service = WorkerAgentService(settings=settings, api_client=client, execution_service=FakeExecutionService())

    response = service.process_once()

    assert response is not None
    assert response["final_status"] == "completed"

    with session_factory() as session:
        worker = WorkerRepository(session).get_by_key("remote-agent-01")
        assert worker is not None
        saved_job = session.query(Job).one()
        assert saved_job.status == JobStatus.COMPLETED
        assert saved_job.last_worker_id == worker.id


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
            "agent_version": CURRENT_VERSION,
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
