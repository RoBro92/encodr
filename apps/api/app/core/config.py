from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from encodr_core.config import ConfigBundle


def bootstrap_config_bundle(project_root: Path | str | None = None) -> "ConfigBundle":
    from encodr_core.config import load_config_bundle

    return load_config_bundle(project_root=project_root)
