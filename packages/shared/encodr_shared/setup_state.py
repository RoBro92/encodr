from __future__ import annotations

import json
from pathlib import Path

from encodr_shared.backend_preferences import DEFAULT_BACKEND_PREFERENCE, coerce_backend_preference


def load_execution_preferences(data_dir: Path | str) -> dict[str, object]:
    state_path = Path(data_dir) / "setup-state.json"
    default = {
        "preferred_backend": DEFAULT_BACKEND_PREFERENCE,
        "allow_cpu_fallback": True,
    }
    if not state_path.exists():
        return default
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    execution_preferences = payload.get("execution_preferences")
    if not isinstance(execution_preferences, dict):
        return default
    return {
        "preferred_backend": coerce_backend_preference(execution_preferences.get("preferred_backend")),
        "allow_cpu_fallback": bool(execution_preferences.get("allow_cpu_fallback", True)),
    }
