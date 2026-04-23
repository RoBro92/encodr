from __future__ import annotations

from pathlib import Path

MARKER_RELATIVE_PATH = ".encodr/worker-marker.txt"


def normalise_path_mappings(mappings: list[dict] | None) -> list[dict]:
    cleaned: list[dict] = []
    for item in mappings or []:
        server_path = str(item.get("server_path") or "").strip()
        worker_path = str(item.get("worker_path") or "").strip()
        label = str(item.get("label") or "").strip() or None
        if not server_path or not worker_path:
            continue
        cleaned.append(
            {
                "label": label,
                "server_path": Path(server_path).expanduser().resolve().as_posix(),
                "worker_path": str(Path(worker_path).expanduser()),
                "marker_relative_path": MARKER_RELATIVE_PATH,
            }
        )
    cleaned.sort(key=lambda item: len(item["server_path"]), reverse=True)
    return cleaned


def mapping_for_server_path(server_path: str | Path, mappings: list[dict] | None) -> dict | None:
    source = Path(server_path).expanduser().resolve().as_posix()
    for item in normalise_path_mappings(mappings):
        prefix = item["server_path"]
        if source == prefix or source.startswith(f"{prefix}/"):
            return item
    return None


def remap_server_path(server_path: str | Path, mappings: list[dict] | None) -> str | None:
    source = Path(server_path).expanduser().resolve().as_posix()
    mapping = mapping_for_server_path(source, mappings)
    if mapping is None:
        return None
    prefix = mapping["server_path"]
    suffix = source[len(prefix):].lstrip("/")
    worker_base = str(Path(mapping["worker_path"]).expanduser())
    if not suffix:
        return worker_base
    return str(Path(worker_base) / suffix)


def ensure_mapping_marker(server_path: str | Path) -> dict[str, object]:
    root = Path(server_path).expanduser().resolve()
    marker = root / MARKER_RELATIVE_PATH
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "Encodr worker path validation marker.\n",
            encoding="utf-8",
        )
        return {
            "status": "usable",
            "message": "Validation marker is ready.",
            "marker_server_path": marker.as_posix(),
            "marker_relative_path": MARKER_RELATIVE_PATH,
        }
    except OSError as error:
        return {
            "status": "marker_write_failed",
            "message": str(error),
            "marker_server_path": marker.as_posix(),
            "marker_relative_path": MARKER_RELATIVE_PATH,
        }


def validate_worker_path_mapping(worker_path: str | Path) -> dict[str, object]:
    base = Path(worker_path).expanduser()
    marker = base / MARKER_RELATIVE_PATH
    if not base.exists():
        return {
            "status": "missing_mapping",
            "message": "Worker path does not exist.",
            "worker_path": str(base),
            "marker_worker_path": marker.as_posix(),
        }
    if not base.is_dir():
        return {
            "status": "invalid_mapping",
            "message": "Worker path is not a directory.",
            "worker_path": str(base),
            "marker_worker_path": marker.as_posix(),
        }
    if not marker.exists():
        return {
            "status": "marker_not_found",
            "message": "Validation marker was not found through the worker mapping.",
            "worker_path": str(base),
            "marker_worker_path": marker.as_posix(),
        }
    if not marker.is_file():
        return {
            "status": "invalid_mapping",
            "message": "Validation marker is not a regular file.",
            "worker_path": str(base),
            "marker_worker_path": marker.as_posix(),
        }
    return {
        "status": "usable",
        "message": "Worker path mapping is valid.",
        "worker_path": str(base),
        "marker_worker_path": marker.as_posix(),
    }

