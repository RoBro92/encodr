from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import WorkerHealthStatus
from encodr_db.repositories import WorkerRepository
from encodr_db.runtime import LOCAL_WORKER_CAPABILITY_SOURCE, LocalWorkerLoop
from encodr_shared.worker_runtime import HardwareProbe
from tests.helpers.api import import_api_module
from tests.helpers.db import create_schema_session_factory


pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_status_prefers_fresh_local_worker_backend_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=REPO_ROOT)
    stale_api_probe = HardwareProbe(
        backend="intel_igpu",
        detected=True,
        usable=False,
        status="failed",
        message="Intel VAAPI runtime validation cannot run because vainfo is not installed.",
        details={"reason_unavailable": "vainfo missing"},
    )
    healthy_worker_probe = {
        "backend": "intel_igpu",
        "preference_key": "prefer_intel_igpu",
        "detected": True,
        "usable_by_ffmpeg": True,
        "ffmpeg_path_verified": True,
        "status": "healthy",
        "message": "Intel VAAPI active; QSV unavailable: MFX session init failed",
        "reason_unavailable": None,
        "recommended_usage": "Intel VAAPI is ready to use in this worker runtime.",
        "selected_backend": "intel_vaapi",
        "usable_backends": ["intel_vaapi"],
        "qsv_unavailable_reason": "MFX session init failed",
        "device_paths": [],
        "details": {"selected_backend": "intel_vaapi"},
    }
    worker_device = {
        "path": "/dev/dri/renderD128",
        "status": "healthy",
        "vendor_name": "Intel",
        "exists": True,
        "readable": True,
        "writable": True,
        "is_character_device": True,
        "mode": "0660",
        "uid": 0,
        "gid": 993,
    }

    with session_factory() as session:
        worker = WorkerRepository(session).upsert_local_worker(
            worker_key=bundle.workers.local.id,
            display_name="Local worker",
            enabled=True,
            preferred_backend="intel_auto",
            allow_cpu_fallback=True,
            max_concurrent_jobs=1,
            schedule_windows=None,
            path_mappings=None,
            scratch_path=str(bundle.workers.local.scratch_dir),
            host_metadata={"hostname": "worker"},
        )
        worker.last_health_status = WorkerHealthStatus.HEALTHY
        worker.last_heartbeat_at = datetime.now(timezone.utc)
        worker.runtime_payload = {
            "capability_source": LOCAL_WORKER_CAPABILITY_SOURCE,
            "hardware_probes": [healthy_worker_probe],
            "runtime_device_paths": [worker_device],
        }
        session.commit()

    with import_api_module("app.services.system") as system_module:
        monkeypatch.setattr(system_module, "probe_execution_backends", lambda _path: [stale_api_probe])
        monkeypatch.setattr(system_module, "discover_runtime_devices", lambda: [])

        payload = system_module.SystemService(
            config_bundle=bundle,
            session_factory=session_factory,
            app_version="test",
        ).runtime_status()

    intel_backend = next(item for item in payload["execution_backends"] if item["backend"] == "intel_igpu")
    assert intel_backend["status"] == "healthy"
    assert intel_backend["selected_backend"] == "intel_vaapi"
    assert payload["runtime_device_paths"] == [worker_device]
    assert all("vainfo" not in warning.lower() for warning in payload["warnings"])


def test_local_backend_validation_uses_fresh_worker_payload_for_vaapi_without_cpu_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=REPO_ROOT)
    stale_api_probe = HardwareProbe(
        backend="intel_igpu",
        detected=True,
        usable=False,
        status="failed",
        message="Intel VAAPI runtime validation cannot run in the API runtime.",
        details={
            "qsv": {"usable": False, "reason_unavailable": "API runtime has no render device"},
            "vaapi": {"usable": False, "reason_unavailable": "API runtime has no render device"},
        },
    )
    healthy_worker_probe = {
        "backend": "intel_igpu",
        "preference_key": "prefer_intel_igpu",
        "preference_keys": ["prefer_intel_igpu", "intel_auto", "intel_qsv", "intel_vaapi", "qsv", "vaapi", "auto"],
        "detected": True,
        "usable_by_ffmpeg": True,
        "ffmpeg_path_verified": True,
        "status": "healthy",
        "message": "Intel VAAPI active; QSV unavailable: MFX session init failed",
        "reason_unavailable": None,
        "selected_backend": "intel_vaapi",
        "usable_backends": ["intel_vaapi"],
        "qsv_unavailable_reason": "MFX session init failed",
        "device_paths": [{"path": "/dev/dri/renderD128", "status": "healthy"}],
        "details": {
            "selected_backend": "intel_vaapi",
            "usable_backends": ["intel_vaapi"],
            "qsv": {"usable": False, "reason_unavailable": "MFX session init failed"},
            "vaapi": {"usable": True, "device_paths": [{"path": "/dev/dri/renderD128", "status": "healthy"}]},
        },
    }

    with session_factory() as session:
        worker = WorkerRepository(session).upsert_local_worker(
            worker_key=bundle.workers.local.id,
            display_name="Local worker",
            enabled=True,
            preferred_backend="intel_vaapi",
            allow_cpu_fallback=False,
            max_concurrent_jobs=1,
            schedule_windows=None,
            path_mappings=None,
            scratch_path=str(bundle.workers.local.scratch_dir),
            host_metadata={"hostname": "worker"},
        )
        worker.last_health_status = WorkerHealthStatus.HEALTHY
        worker.last_heartbeat_at = datetime.now(timezone.utc)
        worker.runtime_payload = {
            "capability_source": LOCAL_WORKER_CAPABILITY_SOURCE,
            "ffmpeg": {"discoverable": True, "status": "healthy"},
            "ffprobe": {"discoverable": True, "status": "healthy"},
            "execution_backends": ["remux", "transcode"],
            "hardware_probes": [healthy_worker_probe],
            "hardware_acceleration": ["intel_igpu", "intel_vaapi"],
            "transcode_backend_usable": True,
            "backend_diagnostic": {
                "requested_backend": "intel_vaapi",
                "normalised_backend": "intel_vaapi",
                "selected_backend": "intel_vaapi",
                "transcode_backend_usable": True,
                "fallback_used": False,
                "qsv_usable": False,
                "qsv_unavailable_reason": "MFX session init failed",
                "vaapi_usable": True,
                "message": "Intel VAAPI is selected and usable.",
            },
            "eligible": True,
            "eligibility_summary": "The local worker can accept execution work.",
        }
        session.commit()

    with import_api_module("app.services.worker") as worker_module:
        monkeypatch.setattr(worker_module, "probe_execution_backends", lambda _path: [stale_api_probe])
        service = worker_module.WorkerService(
            config_bundle=bundle,
            local_worker_loop=LocalWorkerLoop(session_factory, bundle),
            session_factory=session_factory,
            worker_token_service=object(),
            worker_auth_runtime=object(),
        )
        with session_factory() as session:
            service._validate_local_backend_preferences(
                session=session,
                preferred_backend="intel_vaapi",
                allow_cpu_fallback=False,
            )
