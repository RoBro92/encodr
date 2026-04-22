from __future__ import annotations

import json
from pathlib import Path


def load_execution_preferences(data_dir: Path | str) -> dict[str, object]:
    state_path = Path(data_dir) / "setup-state.json"
    default = {
        "preferred_backend": "cpu_only",
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
    preferred_backend = str(execution_preferences.get("preferred_backend") or "cpu_only").strip()
    if preferred_backend not in {
        "cpu_only",
        "prefer_intel_igpu",
        "prefer_nvidia_gpu",
        "prefer_amd_gpu",
    }:
        preferred_backend = "cpu_only"
    return {
        "preferred_backend": preferred_backend,
        "allow_cpu_fallback": bool(execution_preferences.get("allow_cpu_fallback", True)),
    }
