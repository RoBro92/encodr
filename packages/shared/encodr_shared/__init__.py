"""Shared enums, release helpers, and small utility types for encodr."""

from encodr_shared.update import UpdateCheckResult, UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import find_project_root, is_version_newer, parse_version, read_version

__all__ = [
    "UpdateCheckResult",
    "UpdateCheckSettings",
    "UpdateChecker",
    "find_project_root",
    "is_version_newer",
    "parse_version",
    "read_version",
]
