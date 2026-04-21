from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.runtime.worker import WorkerStatusTracker


pytestmark = [pytest.mark.unit]
REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))
import app.services.worker as worker_service_module  # type: ignore  # noqa: E402
from app.schemas.worker import HealthStatus  # type: ignore  # noqa: E402
from app.services.worker import WorkerService  # type: ignore  # noqa: E402
sys.path.remove(str(API_ROOT))


class DummyWorkerLoop:
    def __init__(self) -> None:
        self.worker_name = "worker-local"
        self.status_tracker = WorkerStatusTracker()


def test_local_worker_status_reports_vaapi_from_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_config_bundle(project_root=REPO_ROOT)
    service = WorkerService(
        config_bundle=bundle,
        local_worker_loop=DummyWorkerLoop(),
        session_factory=None,
        worker_token_service=object(),
        worker_auth_runtime=SimpleNamespace(registration_secret="secret"),
    )

    monkeypatch.setattr(
        service,
        "binary_status",
        lambda _path: {
            "configured_path": "ffmpeg",
            "resolved_path": "/usr/bin/ffmpeg",
            "exists": True,
            "executable": True,
            "discoverable": True,
            "status": HealthStatus.HEALTHY,
            "message": "ok",
        },
    )
    monkeypatch.setattr(
        worker_service_module,
        "probe_directory",
        lambda _path, writable_required: {
            "path": str(_path),
            "exists": True,
            "is_directory": True,
            "readable": True,
            "writable": True,
            "status": "healthy",
            "message": "ok",
        },
    )
    monkeypatch.setattr(
        worker_service_module,
        "probe_intel_qsv",
        lambda _path: SimpleNamespace(
            backend="intel_qsv",
            detected=False,
            usable=False,
            status="failed",
            message="no qsv",
            details={},
        ),
    )
    monkeypatch.setattr(
        worker_service_module,
        "probe_vaapi",
        lambda _path: SimpleNamespace(
            backend="vaapi",
            detected=True,
            usable=True,
            status="healthy",
            message="vaapi ready",
            details={},
        ),
    )

    payload = service.status_summary()

    assert payload["hardware_acceleration"] == ["vaapi"]
    assert payload["capabilities"]["vaapi"] is True
    assert payload["hardware_probes"][1]["backend"] == "vaapi"
    assert payload["hardware_probes"][1]["usable"] is True
