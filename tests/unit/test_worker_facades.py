from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from encodr_db.runtime import LocalWorkerLoop, WorkerExecutionService


pytestmark = [pytest.mark.unit]


def test_worker_app_facades_remain_compatibility_imports(repo_root: Path) -> None:
    worker_root = repo_root / "apps" / "worker"
    existing_app_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in list(existing_app_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(worker_root))
    try:
        executor_loop = importlib.import_module("app.executor.loop")
        executor_service = importlib.import_module("app.executor.service")
        planner = importlib.import_module("app.planner")
        probe = importlib.import_module("app.probe")
        verification = importlib.import_module("app.verification")
    finally:
        if str(worker_root) in sys.path:
            sys.path.remove(str(worker_root))
        for name in [name for name in sys.modules if name == "app" or name.startswith("app.")]:
            sys.modules.pop(name, None)
        sys.modules.update(existing_app_modules)

    assert executor_loop.LocalWorkerLoop is LocalWorkerLoop
    assert executor_service.WorkerExecutionService is WorkerExecutionService
    assert callable(planner.build_media_processing_plan)
    assert callable(probe.probe_media_file)
    assert "encodr_core.verification" in (verification.__doc__ or "")

