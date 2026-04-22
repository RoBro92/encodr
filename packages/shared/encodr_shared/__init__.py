"""Shared enums, release helpers, and small utility types for encodr."""

from encodr_shared.setup_state import load_execution_preferences
from encodr_shared.telemetry import collect_runtime_telemetry
from encodr_shared.update import UpdateCheckResult, UpdateCheckSettings, UpdateChecker
from encodr_shared.versioning import find_project_root, is_version_newer, parse_version, read_version
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
    "collect_runtime_telemetry",
    "load_execution_preferences",
    "detect_ffmpeg_hwaccels",
    "discover_runtime_devices",
    "find_project_root",
    "is_version_newer",
    "parse_version",
    "probe_binary",
    "probe_device_node",
    "probe_directory",
    "probe_execution_backends",
    "probe_intel_qsv",
    "probe_vaapi",
    "read_version",
]
