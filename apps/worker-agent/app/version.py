from __future__ import annotations

from pathlib import Path


def read_agent_version() -> str:
    resolved_path = Path(__file__).resolve()
    version_file_candidates = [Path("/app/VERSION")]

    for parent_index in (2, 3):
        if len(resolved_path.parents) > parent_index:
            version_file_candidates.append(resolved_path.parents[parent_index] / "VERSION")

    for version_file in version_file_candidates:
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()

    return "0.0.0+unknown"
