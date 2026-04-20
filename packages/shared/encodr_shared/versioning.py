from __future__ import annotations

from pathlib import Path


VERSION_FILE_NAME = "VERSION"


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in [current, *current.parents]:
        if (candidate / VERSION_FILE_NAME).exists():
            return candidate

    raise FileNotFoundError(f"Unable to locate {VERSION_FILE_NAME} from {current}.")


def read_version(start: Path | None = None) -> str:
    project_root = find_project_root(start)
    return (project_root / VERSION_FILE_NAME).read_text(encoding="utf-8").strip()


def parse_version(version: str) -> tuple[int, ...]:
    core = version.strip().split("-", 1)[0]
    parts = core.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Version '{version}' is not a dotted numeric version.")
    return tuple(int(part) for part in parts)


def is_version_newer(current_version: str, candidate_version: str) -> bool:
    try:
        current = parse_version(current_version)
        candidate = parse_version(candidate_version)
    except ValueError:
        return candidate_version.strip() != current_version.strip()

    max_length = max(len(current), len(candidate))
    current = current + (0,) * (max_length - len(current))
    candidate = candidate + (0,) * (max_length - len(candidate))
    return candidate > current
