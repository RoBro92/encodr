from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from encodr_core.execution import ExecutionResult


pytestmark = [pytest.mark.unit]

WORKER_AGENT_ROOT = Path(__file__).resolve().parents[2] / "apps" / "worker-agent"
sys.path.insert(0, str(WORKER_AGENT_ROOT))
sys.modules.pop("app", None)

import app.version as worker_agent_version  # type: ignore  # noqa: E402
import app.capabilities as worker_agent_capabilities  # type: ignore  # noqa: E402
from app.capabilities import build_capability_summary  # type: ignore  # noqa: E402
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
        if url.endswith("/worker/jobs/request"):
            return {
                "status": "no_job",
                "job": None,
            }
        if "/worker/jobs/" in url and url.endswith("/claim"):
            return {
                "status": "claimed",
                "job_id": "job-1",
                "claimed_at": "2026-04-20T12:02:00Z",
            }
        if "/worker/jobs/" in url and url.endswith("/result"):
            return {
                "job_id": "job-1",
                "final_status": "completed",
                "completed_at": "2026-04-20T12:03:00Z",
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
    assert payload["capability_summary"]["hardware_hints"] == ["cpu_only"]


def test_worker_agent_does_not_claim_vaapi_without_render_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_FFMPEG_PATH": str(tmp_path / "bin" / "ffmpeg"),
            "ENCODR_WORKER_AGENT_FFPROBE_PATH": str(tmp_path / "bin" / "ffprobe"),
            "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(tmp_path / "scratch"),
        }
    )
    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        binary = tmp_path / "bin" / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
    (tmp_path / "scratch").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        worker_agent_capabilities,
        "probe_execution_backends",
        lambda _path: [],
    )

    summary = build_capability_summary(settings)

    assert summary["hardware_hints"] == ["cpu_only"]


def test_worker_agent_rejects_non_positive_heartbeat_interval() -> None:
    with pytest.raises(ValueError, match="ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS"):
        load_settings(
            {
                "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
                "ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS": "0",
            }
        )


def test_worker_agent_process_once_claims_and_submits_result(tmp_path: Path) -> None:
    class FakeExecutionService:
        def execute(self, *, job_id: str, plan_payload: dict, media_payload: dict) -> ExecutionResult:
            del plan_payload, media_payload
            return ExecutionResult(
                mode="remux",
                status="completed",
                command=["ffmpeg", "-i", "input.mkv", "output.mkv"],
                output_path=Path("/media/output.mkv"),
                final_output_path=Path("/media/output.mkv"),
                original_backup_path=Path("/media/input.encodr-backup.mkv"),
                output_size_bytes=123,
                exit_code=0,
                stdout="ok",
                stderr="",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

    requester = FakeRequester()
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-amd-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote AMD Worker",
            "ENCODR_WORKER_AGENT_TOKEN_FILE": str(tmp_path / "worker.token"),
            "ENCODR_WORKER_AGENT_FFMPEG_PATH": str(tmp_path / "bin" / "ffmpeg"),
            "ENCODR_WORKER_AGENT_FFPROBE_PATH": str(tmp_path / "bin" / "ffprobe"),
            "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(tmp_path / "scratch"),
        }
    )
    token_file = tmp_path / "worker.token"
    token_file.write_text("persisted-token", encoding="utf-8")
    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        binary = tmp_path / "bin" / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
    (tmp_path / "scratch").mkdir(parents=True, exist_ok=True)

    def request_json(*, method: str, url: str, body: dict | None = None, bearer_token: str | None = None) -> dict:
        requester.calls.append({"method": method, "url": url, "body": body, "bearer_token": bearer_token})
        if url.endswith("/worker/jobs/request"):
            return {
                "status": "assigned",
                "job": {
                    "job_id": "job-1",
                    "tracked_file_id": "file-1",
                    "plan_snapshot_id": "plan-1",
                    "source_path": "/media/input.mkv",
                    "plan_payload": {
                        "action": "remux",
                        "replace": {
                            "in_place": True,
                            "require_verification": True,
                            "keep_original_until_verified": True,
                            "delete_replaced_source": False,
                        },
                        "container": {"target_container": "mkv"},
                        "selected_streams": {
                            "video_stream_indices": [0],
                            "audio_stream_indices": [1],
                            "subtitle_stream_indices": [],
                            "attachment_stream_indices": [],
                            "data_stream_indices": [],
                        },
                        "video": {"transcode_required": False, "target_codec": None},
                        "policy_context": {"policy_version": 1, "selected_profile_name": "movies-default"},
                        "should_treat_as_protected": False,
                    },
                    "media_payload": {
                        "file_path": "/media/input.mkv",
                        "file_name": "input.mkv",
                        "is_4k": False,
                        "container": {"size_bytes": 123},
                        "video_streams": [{"index": 0, "codec_name": "hevc", "width": 1920, "height": 1080}],
                        "audio_streams": [{"index": 1, "codec_name": "eac3", "language": "eng", "channel_layout": "5.1"}],
                        "subtitle_streams": [],
                        "attachment_streams": [],
                        "data_streams": [],
                    },
                    "requested_worker_type": None,
                    "assignment_state": "assigned",
                    "assigned_worker_id": "worker-1",
                },
            }
        return FakeRequester.request_json(requester, method=method, url=url, body=body, bearer_token=bearer_token)

    requester.request_json = request_json  # type: ignore[attr-defined]
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    service = WorkerAgentService(settings=settings, api_client=client, execution_service=FakeExecutionService())

    response = service.process_once()

    assert response is not None
    assert response["final_status"] == "completed"
    assert any(call["url"].endswith("/worker/jobs/job-1/claim") for call in requester.calls)
    assert any(call["url"].endswith("/worker/jobs/job-1/result") for call in requester.calls)


def test_worker_agent_reports_failure_when_execution_raises(tmp_path: Path) -> None:
    class FailingExecutionService:
        def execute(self, *, job_id: str, plan_payload: dict, media_payload: dict) -> ExecutionResult:
            del job_id, plan_payload, media_payload
            raise RuntimeError("ffmpeg crashed")

    requester = FakeRequester()

    def request_json(*, method: str, url: str, body: dict | None = None, bearer_token: str | None = None) -> dict:
        requester.calls.append({"method": method, "url": url, "body": body, "bearer_token": bearer_token})
        if url.endswith("/worker/jobs/request"):
            return {
                "status": "assigned",
                "job": {
                    "job_id": "job-1",
                    "tracked_file_id": "file-1",
                    "plan_snapshot_id": "plan-1",
                    "source_path": "/media/input.mkv",
                    "plan_payload": {
                        "action": "remux",
                        "replace": {
                            "in_place": True,
                            "require_verification": True,
                            "keep_original_until_verified": True,
                            "delete_replaced_source": False,
                        },
                        "container": {"target_container": "mkv"},
                        "selected_streams": {
                            "video_stream_indices": [0],
                            "audio_stream_indices": [1],
                            "subtitle_stream_indices": [],
                            "attachment_stream_indices": [],
                            "data_stream_indices": [],
                        },
                        "video": {"transcode_required": False, "target_codec": None},
                        "policy_context": {"policy_version": 1, "selected_profile_name": "movies-default"},
                        "should_treat_as_protected": False,
                    },
                    "media_payload": {
                        "file_path": "/media/input.mkv",
                        "file_name": "input.mkv",
                        "is_4k": False,
                        "container": {"size_bytes": 123},
                        "video_streams": [{"index": 0, "codec_name": "hevc", "width": 1920, "height": 1080}],
                        "audio_streams": [{"index": 1, "codec_name": "eac3", "language": "eng", "channel_layout": "5.1"}],
                        "subtitle_streams": [],
                        "attachment_streams": [],
                        "data_streams": [],
                    },
                    "requested_worker_type": None,
                    "assignment_state": "assigned",
                    "assigned_worker_id": "worker-1",
                },
            }
        if "/worker/jobs/" in url and url.endswith("/failure"):
            return {
                "job_id": "job-1",
                "final_status": "failed",
                "completed_at": "2026-04-20T12:03:00Z",
            }
        return FakeRequester.request_json(requester, method=method, url=url, body=body, bearer_token=bearer_token)

    requester.request_json = request_json  # type: ignore[attr-defined]
    client = WorkerApiClient(base_url="http://encodr.test/api", requester=requester)
    settings = load_settings(
        {
            "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
            "ENCODR_WORKER_AGENT_KEY": "remote-amd-01",
            "ENCODR_WORKER_AGENT_DISPLAY_NAME": "Remote AMD Worker",
            "ENCODR_WORKER_AGENT_TOKEN_FILE": str(tmp_path / "worker.token"),
            "ENCODR_WORKER_AGENT_FFMPEG_PATH": str(tmp_path / "bin" / "ffmpeg"),
            "ENCODR_WORKER_AGENT_FFPROBE_PATH": str(tmp_path / "bin" / "ffprobe"),
            "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(tmp_path / "scratch"),
        }
    )
    token_file = tmp_path / "worker.token"
    token_file.write_text("persisted-token", encoding="utf-8")
    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        binary = tmp_path / "bin" / name
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
    (tmp_path / "scratch").mkdir(parents=True, exist_ok=True)

    service = WorkerAgentService(settings=settings, api_client=client, execution_service=FailingExecutionService())

    with pytest.raises(RuntimeError, match="ffmpeg crashed"):
        service.process_once()

    assert any(call["url"].endswith("/worker/jobs/job-1/claim") for call in requester.calls)
    failure_calls = [call for call in requester.calls if call["url"].endswith("/worker/jobs/job-1/failure")]
    assert len(failure_calls) == 1
    assert failure_calls[0]["body"]["failure_category"] == "worker_agent_error"
    assert failure_calls[0]["body"]["failure_message"] == "ffmpeg crashed"


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
