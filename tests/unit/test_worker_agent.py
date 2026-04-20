from __future__ import annotations

import sys
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit]

WORKER_AGENT_ROOT = Path(__file__).resolve().parents[2] / "apps" / "worker-agent"
sys.path.insert(0, str(WORKER_AGENT_ROOT))
sys.modules.pop("app", None)

import app.version as worker_agent_version  # type: ignore  # noqa: E402
from app.client import WorkerApiClient  # type: ignore  # noqa: E402
from app.config import load_settings  # type: ignore  # noqa: E402
from app.service import WorkerAgentService  # type: ignore  # noqa: E402
from app.version import read_agent_version  # type: ignore  # noqa: E402

for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
    sys.modules.pop(module_name, None)
sys.path.remove(str(WORKER_AGENT_ROOT))


class FakeRequester:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request_json(self, *, method: str, url: str, body: dict | None = None, bearer_token: str | None = None) -> dict:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "body": body,
                "bearer_token": bearer_token,
            }
        )
        if url.endswith("/worker/register"):
            return {
                "worker_id": "worker-1",
                "worker_key": "remote-amd-01",
                "worker_token": "issued-token",
                "registration_status": "registered",
                "enabled": True,
                "worker_type": "remote",
                "display_name": "Remote AMD Worker",
                "health_status": "healthy",
                "health_summary": "Ready",
                "issued_at": "2026-04-20T12:00:00Z",
            }
        return {
            "worker_id": "worker-1",
            "worker_key": "remote-amd-01",
            "enabled": True,
            "registration_status": "registered",
            "health_status": "healthy",
            "health_summary": "Heartbeat ok",
            "heartbeat_at": "2026-04-20T12:01:00Z",
        }


def test_worker_agent_register_then_heartbeat_happy_path(tmp_path: Path) -> None:
    requester = FakeRequester()
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-amd-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote AMD Worker",
            "ENCODR_WORKER_AGENT_REGISTRATION_SECRET": "bootstrap-secret",
            "ENCODR_WORKER_AGENT_TOKEN_FILE": str(tmp_path / "worker.token"),
            "ENCODR_WORKER_AGENT_QUEUE": "remote-amd",
        }
    )
    service = WorkerAgentService(settings=settings, api_client=client)

    registration = service.register()
    heartbeat = service.heartbeat()

    assert registration.worker_token == "issued-token"
    assert heartbeat["worker_key"] == "remote-amd-01"
    assert requester.calls[0]["url"].endswith("/worker/register")
    assert requester.calls[1]["url"].endswith("/worker/heartbeat")
    assert requester.calls[1]["bearer_token"] == "issued-token"


def test_worker_agent_uses_existing_token_without_reregistering(tmp_path: Path) -> None:
    requester = FakeRequester()
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    token_file = tmp_path / "worker.token"
    token_file.write_text("persisted-token", encoding="utf-8")
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-amd-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote AMD Worker",
            "ENCODR_WORKER_AGENT_TOKEN_FILE": str(token_file),
        }
    )
    service = WorkerAgentService(settings=settings, api_client=client)

    heartbeat = service.heartbeat()

    assert heartbeat["worker_key"] == "remote-amd-01"
    assert len(requester.calls) == 1
    assert requester.calls[0]["bearer_token"] == "persisted-token"


def test_worker_agent_registration_payload_is_built_from_settings(tmp_path: Path) -> None:
    requester = FakeRequester()
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-intel-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote Intel Worker",
            "ENCODR_WORKER_AGENT_REGISTRATION_SECRET": "bootstrap-secret",
            "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(tmp_path / "scratch"),
            "ENCODR_WORKER_AGENT_MEDIA_MOUNTS": "/media/a,/media/b",
        }
    )
    service = WorkerAgentService(settings=settings, api_client=client)

    payload = service.build_registration_payload()

    assert payload["worker_key"] == "remote-intel-01"
    assert payload["runtime_summary"]["scratch_dir"] == str(tmp_path / "scratch")
    assert payload["runtime_summary"]["media_mounts"] == ["/media/a", "/media/b"]
    assert "intel_qsv" in payload["capability_summary"]["hardware_hints"]


def test_worker_agent_rejects_non_positive_heartbeat_interval() -> None:
    with pytest.raises(ValueError, match="ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS"):
        load_settings(
            {
                "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
                "ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS": "0",
            }
        )


def test_worker_agent_version_lookup_handles_shallow_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResolvedPath:
        parents = (Path("/virtual"),)

    class FakePath:
        def __init__(self, value: str) -> None:
            self.value = value

        def resolve(self) -> FakeResolvedPath:
            return FakeResolvedPath()

        def exists(self) -> bool:
            return False

        def read_text(self, encoding: str = "utf-8") -> str:
            raise AssertionError("read_text should not be called when no version file exists")

    monkeypatch.setattr(worker_agent_version, "Path", FakePath)

    assert read_agent_version() == "0.0.0+unknown"
