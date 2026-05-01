from __future__ import annotations

import copy
from typing import Any

RUNTIME_SUMMARY_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("queue", None),
    ("scratch_dir", None),
    ("scratch_status", None),
    ("media_mounts", []),
    ("media_paths", []),
    ("path_mappings", []),
    ("preferred_backend", None),
    ("allow_cpu_fallback", None),
    ("max_concurrent_jobs", None),
    ("schedule_windows", []),
    ("current_job_id", None),
    ("current_backend", None),
    ("selected_backend", None),
    ("backend_fallback_used", None),
    ("backend_fallback_reason", None),
    ("qsv_usable", None),
    ("qsv_unavailable_reason", None),
    ("vaapi_usable", None),
    ("vaapi_unavailable_reason", None),
    ("backend_diagnostic", None),
    ("current_stage", None),
    ("current_progress_percent", None),
    ("current_progress_updated_at", None),
    ("telemetry", None),
    ("last_completed_job_id", None),
    ("ffmpeg", None),
    ("ffprobe", None),
    ("execution_backends", []),
    ("hardware_acceleration", []),
    ("hardware_probes", []),
    ("runtime_device_paths", []),
    ("eligible", None),
    ("eligibility_summary", None),
    ("transcode_backend_usable", None),
    ("capability_source", None),
    ("capability_checked_at", None),
)

RUNTIME_SUMMARY_KEYS = tuple(key for key, _default in RUNTIME_SUMMARY_DEFAULTS)


def clean_runtime_summary_payload(payload: dict[str, Any] | None) -> dict[str, object]:
    source = payload or {}
    return {
        key: copy.deepcopy(source[key]) if key in source else copy.deepcopy(default)
        for key, default in RUNTIME_SUMMARY_DEFAULTS
    }


def merge_runtime_summary_preferences(
    runtime_summary: dict[str, Any] | None,
    *,
    preferred_backend: str,
    allow_cpu_fallback: bool,
    max_concurrent_jobs: int,
    schedule_windows: list[dict] | None,
    scratch_path: str | None,
    path_mappings: list[dict[str, object]] | None,
) -> dict[str, object]:
    merged: dict[str, object] = copy.deepcopy(runtime_summary or {})
    if scratch_path:
        merged["scratch_dir"] = scratch_path
        if merged.get("scratch_status") is None:
            merged["scratch_status"] = {
                "path": scratch_path,
                "status": "unknown",
                "message": "Scratch validation has not been reported by the worker yet.",
            }
    if path_mappings is not None:
        merged["path_mappings"] = copy.deepcopy(path_mappings)
    merged.update(
        {
            "preferred_backend": preferred_backend,
            "allow_cpu_fallback": allow_cpu_fallback,
            "max_concurrent_jobs": max_concurrent_jobs,
            "schedule_windows": copy.deepcopy(schedule_windows or []),
        }
    )
    return clean_runtime_summary_payload(merged)
