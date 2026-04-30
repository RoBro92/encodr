from __future__ import annotations

from pathlib import Path


BACKUP_FILE_REASON = "Encodr backup files are managed separately and cannot be processed."
RESTORED_REPLACEMENT_REASON = "Encodr restored replacement files cannot be queued for processing."
TEMP_FILE_REASON = "Encodr temporary or staged output files cannot be processed."
SCRATCH_FILE_REASON = "Encodr scratch workspace files cannot be processed."


def encodr_exclusion_reason(path: Path | str, *, scratch_dir: Path | str | None = None) -> str | None:
    candidate = Path(path)
    name = candidate.name.lower()

    if scratch_dir is not None and _is_relative_to(candidate, Path(scratch_dir)):
        return SCRATCH_FILE_REASON
    if ".encodr-backup." in name or name.endswith(".encodr-backup"):
        return BACKUP_FILE_REASON
    if ".encodr-restored-replacement." in name or name.endswith(".encodr-restored-replacement"):
        return RESTORED_REPLACEMENT_REASON
    if ".tmp." in name or name.endswith(".tmp"):
        return TEMP_FILE_REASON
    if ".partial." in name or name.endswith(".partial"):
        return TEMP_FILE_REASON
    if ".encodr-scratch." in name or name.startswith("encodr-scratch."):
        return SCRATCH_FILE_REASON
    return None


def is_encodr_excluded_path(path: Path | str, *, scratch_dir: Path | str | None = None) -> bool:
    return encodr_exclusion_reason(path, scratch_dir=scratch_dir) is not None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        resolved_path = path.expanduser().resolve(strict=False)
        resolved_parent = parent.expanduser().resolve(strict=False)
        resolved_path.relative_to(resolved_parent)
        return True
    except (OSError, RuntimeError, ValueError):
        return False
