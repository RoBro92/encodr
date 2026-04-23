"""Shared enums, release helpers, and small utility types for encodr."""

from encodr_shared.path_mappings import (
    MARKER_RELATIVE_PATH,
    ensure_mapping_marker,
    mapping_for_server_path,
    normalise_path_mappings,
    remap_server_path,
    validate_worker_path_mapping,
)
from encodr_shared.setup_state import load_execution_preferences
from encodr_shared.telemetry import collect_runtime_telemetry
from encodr_shared.update import UpdateCheckResult, UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import find_project_root, is_version_newer, parse_version, read_version
from encodr_shared.worker_policy import recommend_worker_concurrency
from encodr_shared.worker_runtime import (
    detect_ffmpeg_hwaccels,
    discover_runtime_devices,
    probe_binary,
    probe_device_node,
    probe_directory,
    probe_execution_backends,
    probe_intel_qsv,
    probe_vaapi,
)

__all__ = [
    "UpdateCheckResult",
    "UpdateCheckSettings",
    "UpdateChecker",
    "MARKER_RELATIVE_PATH",
    "collect_runtime_telemetry",
    "load_execution_preferences",
    "detect_ffmpeg_hwaccels",
    "discover_runtime_devices",
    "ensure_mapping_marker",
    "find_project_root",
    "is_version_newer",
    "mapping_for_server_path",
    "normalise_path_mappings",
    "parse_version",
    "probe_binary",
    "probe_device_node",
    "probe_directory",
    "probe_execution_backends",
    "probe_intel_qsv",
    "probe_vaapi",
    "read_version",
    "recommend_worker_concurrency",
    "remap_server_path",
    "validate_worker_path_mapping",
]
