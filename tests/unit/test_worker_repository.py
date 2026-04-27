from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_shared.worker_runtime import HardwareProbe
from encodr_db.models import WorkerHealthStatus
from encodr_db.repositories import WorkerRepository
from encodr_db.runtime import LOCAL_WORKER_CAPABILITY_SOURCE, LocalWorkerLoop
from tests.helpers.db import create_schema_session_factory


pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_worker_registration_and_lookup_updates_existing_record() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        first = repository.register_remote_worker(
            worker_key="worker-remote-1",
            display_name="Remote Worker 1",
            auth_token_hash="hash-1",
            host_metadata={"hostname": "remote-a"},
            capability_payload={"execution_modes": ["remux"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": []},
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Ready",
            registered_at=datetime.now(timezone.utc),
        )
        second = repository.register_remote_worker(
            worker_key="worker-remote-1",
            display_name="Remote Worker 1B",
            auth_token_hash="hash-2",
            host_metadata={"hostname": "remote-b"},
            capability_payload={"execution_modes": ["remux", "transcode"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": [{"name": "ffmpeg"}]},
            health_status=WorkerHealthStatus.DEGRADED,
            health_summary="Warning",
            registered_at=datetime.now(timezone.utc),
        )

        assert first.id == second.id
        assert second.display_name == "Remote Worker 1B"
        assert repository.get_by_key("worker-remote-1").auth_token_hash == "hash-2"


def test_worker_heartbeat_updates_last_seen_and_capabilities() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        worker = repository.register_remote_worker(
            worker_key="worker-remote-2",
            display_name="Remote Worker 2",
            auth_token_hash="hash-2",
            host_metadata={"hostname": "remote"},
            capability_payload={"execution_modes": ["remux"]},
            runtime_payload=None,
            binary_payload=None,
            health_status=WorkerHealthStatus.UNKNOWN,
            health_summary=None,
            registered_at=datetime.now(timezone.utc),
        )
        heartbeat_at = datetime.now(timezone.utc)
        repository.record_heartbeat(
            worker,
            heartbeat_at=heartbeat_at,
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Heartbeat healthy",
            capability_payload={"execution_modes": ["remux", "transcode"]},
            runtime_payload={"queue": "remote"},
            binary_payload={"binaries": [{"name": "ffprobe"}]},
            host_metadata={"hostname": "remote-updated"},
        )

        assert worker.last_seen_at == heartbeat_at
        assert worker.last_health_status == WorkerHealthStatus.HEALTHY
        assert worker.capability_payload["execution_modes"] == ["remux", "transcode"]
        assert worker.runtime_payload["queue"] == "remote"


def test_local_worker_capability_refresh_replaces_stale_vainfo_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=REPO_ROOT)

    stale_probe = {
        "backend": "intel_igpu",
        "preference_key": "prefer_intel_igpu",
        "detected": True,
        "usable_by_ffmpeg": False,
        "ffmpeg_path_verified": False,
        "status": "failed",
        "message": "Intel iGPU passthrough is not fully usable in this runtime.",
        "reason_unavailable": "vainfo missing",
        "recommended_usage": "Install vainfo.",
        "device_paths": [],
        "details": {
            "reason_unavailable": "vainfo missing",
            "vaapi": {
                "usable": False,
                "message": "Intel VAAPI runtime validation cannot run because vainfo is not installed.",
                "vainfo": {
                    "configured_path": "vainfo",
                    "resolved_path": None,
                    "discoverable": False,
                    "which": {
                        "command": "which vainfo",
                        "returncode": 1,
                        "stdout": None,
                        "stderr": None,
                    },
                },
            },
        },
    }

    with session_factory() as session:
        repository = WorkerRepository(session)
        worker = repository.upsert_local_worker(
            worker_key=bundle.workers.local.id,
            display_name="Local worker",
            enabled=True,
            preferred_backend="prefer_intel_igpu",
            allow_cpu_fallback=True,
            max_concurrent_jobs=1,
            schedule_windows=None,
            path_mappings=None,
            scratch_path=str(bundle.workers.local.scratch_dir),
            host_metadata={"hostname": "api-container"},
        )
        worker.capability_payload = {
            "execution_modes": ["remux", "transcode"],
            "hardware_hints": ["cpu_only"],
            "binary_support": {"ffmpeg": True, "ffprobe": True, "vainfo": False},
            "hardware_probes": [stale_probe],
            "capability_source": LOCAL_WORKER_CAPABILITY_SOURCE,
        }
        worker.runtime_payload = {
            "capability_source": LOCAL_WORKER_CAPABILITY_SOURCE,
            "hardware_probes": [stale_probe],
        }
        session.commit()

    def fake_binary(path):
        name = str(path)
        resolved = "/usr/bin/vainfo" if name == "vainfo" else f"/usr/bin/{Path(name).name}"
        return type(
            "BinaryProbe",
            (),
            {
                "configured_path": name,
                "resolved_path": resolved,
                "exists": True,
                "executable": True,
                "discoverable": True,
                "status": "healthy",
                "message": "Binary is discoverable and executable.",
            },
        )()

    current_intel_probe = HardwareProbe(
        backend="intel_igpu",
        detected=True,
        usable=True,
        status="healthy",
        message="Intel iGPU is available via VAAPI in this runtime.",
        details={
            "ffmpeg_path_verified": True,
            "reason_unavailable": None,
            "device_paths": [{"path": "/dev/dri/renderD128", "status": "healthy"}],
            "vaapi": {
                "usable": True,
                "message": "Intel VAAPI is available and validated in the current runtime.",
                "vainfo": {
                    "configured_path": "vainfo",
                    "resolved_path": "/usr/bin/vainfo",
                    "discoverable": True,
                    "which": {
                        "command": "which vainfo",
                        "returncode": 0,
                        "stdout": "/usr/bin/vainfo",
                        "stderr": None,
                    },
                },
            },
        },
    )
    current_cpu_probe = HardwareProbe(
        backend="cpu",
        detected=True,
        usable=True,
        status="healthy",
        message="CPU execution is available.",
        details={"reason_unavailable": None},
    )
    monkeypatch.setattr("encodr_db.runtime.worker.probe_binary", fake_binary)
    monkeypatch.setattr(
        "encodr_db.runtime.worker.probe_which",
        lambda _name: {
            "command": "which vainfo",
            "returncode": 0,
            "stdout": "/usr/bin/vainfo",
            "stderr": None,
        },
    )
    monkeypatch.setattr(
        "encodr_db.runtime.worker.probe_directory",
        lambda path, writable_required: {
            "path": str(path),
            "status": "healthy",
            "message": "Path is ready.",
            "writable_required": writable_required,
        },
    )
    monkeypatch.setattr(
        "encodr_db.runtime.worker.probe_execution_backends",
        lambda _path: [current_cpu_probe, current_intel_probe],
    )
    monkeypatch.setattr(
        "encodr_db.runtime.worker.discover_runtime_devices",
        lambda: [{"path": "/dev/dri/renderD128", "status": "healthy", "vendor_name": "Intel"}],
    )

    loop = LocalWorkerLoop(
        session_factory,
        bundle,
        capability_refresh_interval_seconds=3600,
    )

    assert loop.refresh_runtime_capabilities(force=True) is True

    with session_factory() as session:
        refreshed = WorkerRepository(session).get_local_worker(bundle.workers.local.id)
        assert refreshed is not None
        assert refreshed.capability_payload["binary_support"]["vainfo"] is True
        assert refreshed.capability_payload["hardware_hints"] == ["intel_igpu"]
        assert refreshed.runtime_payload["hardware_probes"][1]["reason_unavailable"] is None
        assert refreshed.runtime_payload["hardware_probes"][1]["details"]["vaapi"]["vainfo"]["which"] == {
            "command": "which vainfo",
            "returncode": 0,
            "stdout": "/usr/bin/vainfo",
            "stderr": None,
        }
        vainfo_binary = next(item for item in refreshed.binary_payload["binaries"] if item["name"] == "vainfo")
        assert vainfo_binary["resolved_path"] == "/usr/bin/vainfo"


def test_worker_enable_disable_updates_registration_state() -> None:
    _, session_factory = create_schema_session_factory()

    with session_factory() as session:
        repository = WorkerRepository(session)
        worker = repository.register_remote_worker(
            worker_key="worker-remote-3",
            display_name="Remote Worker 3",
            auth_token_hash="hash-3",
            host_metadata=None,
            capability_payload=None,
            runtime_payload=None,
            binary_payload=None,
            health_status=WorkerHealthStatus.HEALTHY,
            health_summary="Ready",
            registered_at=datetime.now(timezone.utc),
        )

        repository.set_enabled(worker, enabled=False)
        assert worker.enabled is False
        assert worker.last_health_status == WorkerHealthStatus.UNKNOWN

        repository.set_enabled(worker, enabled=True)
        assert worker.enabled is True
