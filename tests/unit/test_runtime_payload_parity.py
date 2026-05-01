from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import Worker, WorkerType
from encodr_db.runtime.worker import build_local_worker_capability_report
from encodr_shared import RUNTIME_SUMMARY_KEYS, clean_runtime_summary_payload
from encodr_shared.worker_runtime import BinaryProbe, HardwareProbe
from tests.helpers.api import import_api_module

pytestmark = [pytest.mark.unit]


@contextmanager
def isolated_app_import(app_root: Path) -> Iterator[None]:
    existing_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in list(existing_modules):
        sys.modules.pop(name, None)

    sys.path.insert(0, str(app_root))
    try:
        yield
    finally:
        if str(app_root) in sys.path:
            sys.path.remove(str(app_root))
        for name in [name for name in sys.modules if name == "app" or name.startswith("app.")]:
            sys.modules.pop(name, None)
        sys.modules.update(existing_modules)


def test_runtime_summary_payloads_keep_api_local_and_agent_parity(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_config_bundle(project_root=repo_root)
    backend_probes = _backend_probes()
    worker = Worker(
        worker_key="worker-local",
        display_name="Local Worker",
        worker_type=WorkerType.LOCAL,
        enabled=True,
        preferred_backend="intel_auto",
        allow_cpu_fallback=True,
        max_concurrent_jobs=2,
        schedule_windows=[],
        path_mappings=[],
        scratch_path=str(bundle.workers.local.scratch_dir),
    )

    import encodr_db.runtime.worker as local_runtime

    monkeypatch.setattr(local_runtime, "_binary_status_payload", lambda path, name=None: _binary_payload(path))
    monkeypatch.setattr(local_runtime, "probe_directory", _directory_payload)
    monkeypatch.setattr(local_runtime, "probe_execution_backends", lambda _path: backend_probes)
    monkeypatch.setattr(local_runtime, "discover_runtime_devices", lambda: [])
    monkeypatch.setattr(
        local_runtime,
        "collect_runtime_telemetry",
        lambda current_backend=None: {"current_backend": current_backend},
    )

    local_payload = build_local_worker_capability_report(
        bundle,
        worker=worker,
        worker_name="worker-local",
    )["runtime_summary"]

    with import_api_module("app.services.worker") as api_worker:
        api_payload = api_worker.WorkerService._clean_runtime_summary(local_payload)

    worker_agent_root = repo_root / "apps" / "worker-agent"
    with isolated_app_import(worker_agent_root):
        agent_capabilities = importlib.import_module("app.capabilities")
        agent_config = importlib.import_module("app.config")
        monkeypatch.setattr(agent_capabilities, "probe_binary", lambda path: _binary_probe(path))
        monkeypatch.setattr(agent_capabilities, "probe_directory", _directory_payload)
        monkeypatch.setattr(agent_capabilities, "probe_execution_backends", lambda _path: backend_probes)
        monkeypatch.setattr(agent_capabilities, "discover_runtime_devices", lambda: [])
        monkeypatch.setattr(
            agent_capabilities,
            "collect_runtime_telemetry",
            lambda current_backend=None: {"current_backend": current_backend},
        )
        settings = agent_config.load_settings(
            {
                "ENCODR_WORKER_AGENT_API_BASE_URL": "http://encodr.test/api",
                "ENCODR_WORKER_AGENT_PREFERRED_BACKEND": "intel_auto",
                "ENCODR_WORKER_AGENT_SCRATCH_DIR": str(bundle.workers.local.scratch_dir),
                "ENCODR_WORKER_AGENT_MEDIA_MOUNTS": "/media",
            }
        )
        agent_payload = agent_capabilities.build_runtime_summary(
            settings,
            backend_probes=backend_probes,
            ffmpeg_probe=_binary_probe("ffmpeg"),
        )

    for payload in (local_payload, api_payload, agent_payload):
        assert set(RUNTIME_SUMMARY_KEYS).issubset(payload.keys())

    local_clean = clean_runtime_summary_payload(local_payload)
    agent_clean = clean_runtime_summary_payload(agent_payload)
    for key in (
        "preferred_backend",
        "allow_cpu_fallback",
        "selected_backend",
        "backend_fallback_used",
        "qsv_usable",
        "vaapi_usable",
        "transcode_backend_usable",
        "execution_backends",
        "hardware_acceleration",
    ):
        assert api_payload[key] == local_clean[key]
        assert agent_clean[key] == local_clean[key]


def test_deferred_app_package_rename_imports_remain_isolated(repo_root: Path) -> None:
    api_root = repo_root / "apps" / "api"
    worker_agent_root = repo_root / "apps" / "worker-agent"

    with isolated_app_import(api_root):
        api_setup = importlib.import_module("app.services.setup")
        assert _module_is_under(api_setup, api_root)

    with isolated_app_import(worker_agent_root):
        agent_config = importlib.import_module("app.config")
        assert _module_is_under(agent_config, worker_agent_root)

    with isolated_app_import(api_root):
        api_worker = importlib.import_module("app.services.worker")
        assert _module_is_under(api_worker, api_root)


def _backend_probes() -> list[HardwareProbe]:
    return [
        HardwareProbe(
            backend="cpu",
            detected=True,
            usable=True,
            status="healthy",
            message="CPU execution is available.",
            details={},
        ),
        HardwareProbe(
            backend="intel_igpu",
            detected=True,
            usable=True,
            status="healthy",
            message="Intel QSV is available and FFmpeg can initialise it.",
            details={
                "ffmpeg_path_verified": True,
                "selected_backend": "intel_qsv",
                "usable_backends": ["intel_qsv", "intel_vaapi"],
                "qsv": {"usable": True},
                "vaapi": {"usable": True},
            },
        ),
    ]


def _binary_probe(path: object) -> BinaryProbe:
    return BinaryProbe(
        configured_path=str(path),
        resolved_path="/usr/bin/ffmpeg",
        exists=True,
        executable=True,
        discoverable=True,
        status="healthy",
        message="Binary is discoverable and executable.",
    )


def _binary_payload(path: object) -> dict[str, object]:
    probe = _binary_probe(path)
    return {
        "configured_path": probe.configured_path,
        "resolved_path": probe.resolved_path,
        "exists": probe.exists,
        "executable": probe.executable,
        "discoverable": probe.discoverable,
        "status": probe.status,
        "message": probe.message,
    }


def _directory_payload(path: object, writable_required: bool) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "is_directory": True,
        "readable": True,
        "writable": True,
        "writable_required": writable_required,
        "status": "healthy",
        "message": "Directory is ready.",
    }


def _module_is_under(module: ModuleType, root: Path) -> bool:
    module_file = Path(str(module.__file__)).resolve()
    try:
        module_file.relative_to(root.resolve())
    except ValueError:
        return False
    return True
