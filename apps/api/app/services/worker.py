from __future__ import annotations

import os
from pathlib import Path
import shutil

from encodr_core.config import ConfigBundle
from encodr_db.runtime import LocalWorkerLoop, WorkerRunSummary


class WorkerService:
    def __init__(self, *, config_bundle: ConfigBundle, local_worker_loop: LocalWorkerLoop) -> None:
        self.config_bundle = config_bundle
        self.local_worker_loop = local_worker_loop

    def run_once(self) -> WorkerRunSummary:
        return self.local_worker_loop.run_once_with_summary()

    def binary_status(self, configured_path: Path | str) -> dict[str, object]:
        resolved = Path(configured_path)
        if resolved.is_absolute():
            exists = resolved.exists()
            executable = exists and os.access(resolved, os.X_OK)
            discoverable = executable
        else:
            exists = shutil.which(str(configured_path)) is not None
            executable = exists
            discoverable = exists
        return {
            "configured_path": str(configured_path),
            "exists": exists,
            "executable": executable,
            "discoverable": discoverable,
        }
