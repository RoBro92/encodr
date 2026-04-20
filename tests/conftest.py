from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

for package_path in (
    REPO_ROOT / "packages" / "core",
    REPO_ROOT / "packages" / "shared",
    REPO_ROOT / "packages" / "db",
    REPO_ROOT / "apps" / "worker",
):
    path_as_text = str(package_path)
    if path_as_text not in sys.path:
        sys.path.insert(0, path_as_text)
