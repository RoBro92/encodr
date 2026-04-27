from __future__ import annotations

import os
import platform

from app.config import WorkerAgentSettings
from app.version import read_agent_version
from encodr_shared import collect_runtime_telemetry, recommend_worker_concurrency, validate_worker_path_mapping
from encodr_core.execution import normalise_backend_preference
from encodr_shared.worker_runtime import probe_binary, probe_directory, probe_execution_backends, probe_which


def _serialise_backend_probe(probe) -> dict[str, object]:
    preference_key = {
        "cpu": "cpu_only",
        "intel_igpu": "prefer_intel_igpu",
        "nvidia_gpu": "prefer_nvidia_gpu",
        "amd_gpu": "prefer_amd_gpu",
    }.get(probe.backend, probe.backend)
    return {
        "backend": probe.backend,
        "preference_key": preference_key,
        "detected": probe.detected,
        "usable_by_ffmpeg": probe.usable,
        "ffmpeg_path_verified": bool(probe.details.get("ffmpeg_path_verified", probe.usable)),
        "status": probe.status,
        "message": probe.message,
        "reason_unavailable": probe.details.get("reason_unavailable"),
        "recommended_usage": probe.details.get("recommended_usage"),
        "device_paths": probe.details.get("device_paths", []),
        "details": probe.details,
    }


def _binary_summary_item(name: str, configured_path: str | os.PathLike[str]) -> dict[str, object]:
    probe = probe_binary(configured_path)
    item: dict[str, object] = {
        "name": name,
        "configured_path": probe.configured_path,
        "resolved_path": probe.resolved_path,
        "exists": probe.exists,
        "executable": probe.executable,
        "discoverable": probe.discoverable,
        "status": probe.status,
        "message": probe.message,
    }
    if name == "vainfo":
        item["which"] = probe_which("vainfo")
    return item


def build_capability_summary(
    settings: WorkerAgentSettings,
    runtime_configuration: dict[str, object] | None = None,
) -> dict[str, object]:
    ffmpeg = probe_binary(settings.ffmpeg_path)
    ffprobe = probe_binary(settings.ffprobe_path)
    execution_modes: list[str] = []
    if ffmpeg.discoverable:
        execution_modes.extend(["remux", "transcode"])
    backend_probes = probe_execution_backends(settings.ffmpeg_path) if ffmpeg.discoverable else []

    hardware_hints: list[str] = [
        probe.backend
        for probe in backend_probes
        if probe.backend != "cpu" and probe.usable
    ]
    if not hardware_hints:
        hardware_hints.append("cpu_only")
    recommended_concurrency, recommendation_reason = recommend_worker_concurrency(
        cpu_count=os.cpu_count(),
        hardware_hints=hardware_hints,
    )
    max_concurrent_jobs = (
        int(runtime_configuration.get("max_concurrent_jobs", recommended_concurrency))
        if isinstance(runtime_configuration, dict)
        else recommended_concurrency
    )

    return {
        "execution_modes": execution_modes,
        "supported_video_codecs": ["h264", "hevc", "av1"] if ffmpeg.discoverable else [],
        "supported_audio_codecs": [],
        "hardware_hints": hardware_hints,
        "binary_support": {"ffmpeg": ffmpeg.discoverable, "ffprobe": ffprobe.discoverable},
        "max_concurrent_jobs": max_concurrent_jobs,
        "recommended_concurrency": recommended_concurrency,
        "recommended_concurrency_reason": recommendation_reason,
        "tags": ["remote", settings.queue],
        "hardware_probes": [_serialise_backend_probe(probe) for probe in backend_probes],
    }


def build_host_summary() -> dict[str, object]:
    return {
        "hostname": platform.node() or None,
        "platform": platform.platform(),
        "agent_version": read_agent_version(),
        "python_version": platform.python_version(),
    }


def build_runtime_summary(
    settings: WorkerAgentSettings,
    runtime_configuration: dict[str, object] | None = None,
) -> dict[str, object]:
    configured = runtime_configuration or {}
    scratch_dir = str(configured.get("scratch_dir") or settings.scratch_dir or ".")
    path_mappings: list[dict[str, object]] = []
    for item in configured.get("path_mappings", []) if isinstance(configured, dict) else []:
        worker_path = str(item.get("worker_path") or "").strip()
        if not worker_path:
            continue
        validation = validate_worker_path_mapping(worker_path)
        path_mappings.append(
            {
                "label": item.get("label"),
                "server_path": item.get("server_path"),
                "worker_path": worker_path,
                "marker_relative_path": item.get("marker_relative_path"),
                "validation_status": validation.get("status"),
                "validation_message": validation.get("message"),
                "marker_server_path": item.get("marker_server_path"),
                "marker_worker_path": validation.get("marker_worker_path"),
            }
        )
    return {
        "queue": settings.queue,
        "scratch_dir": scratch_dir,
        "scratch_status": probe_directory(scratch_dir, writable_required=True),
        "media_mounts": list(settings.media_mounts),
        "path_mappings": path_mappings,
        "preferred_backend": str(configured.get("preferred_backend") or settings.preferred_backend),
        "allow_cpu_fallback": bool(
            configured.get("allow_cpu_fallback")
            if isinstance(configured, dict) and configured.get("allow_cpu_fallback") is not None
            else settings.allow_cpu_fallback
        ),
        "max_concurrent_jobs": (
            int(configured.get("max_concurrent_jobs"))
            if isinstance(configured, dict) and configured.get("max_concurrent_jobs") is not None
            else 1
        ),
        "schedule_windows": list(configured.get("schedule_windows", [])) if isinstance(configured, dict) else [],
        "telemetry": collect_runtime_telemetry(),
        "last_completed_job_id": None,
    }


def build_binary_summary(settings: WorkerAgentSettings) -> list[dict[str, object]]:
    return [
        _binary_summary_item("ffmpeg", settings.ffmpeg_path),
        _binary_summary_item("ffprobe", settings.ffprobe_path),
        _binary_summary_item("vainfo", "vainfo"),
    ]


def build_worker_health(
    settings: WorkerAgentSettings,
    runtime_configuration: dict[str, object] | None = None,
) -> tuple[str, str]:
    ffmpeg = probe_binary(settings.ffmpeg_path)
    ffprobe = probe_binary(settings.ffprobe_path)
    runtime_summary = build_runtime_summary(settings, runtime_configuration=runtime_configuration)
    scratch = runtime_summary.get("scratch_status") or probe_directory(settings.scratch_dir or ".", writable_required=True)
    backends = probe_execution_backends(settings.ffmpeg_path) if ffmpeg.discoverable else []
    preferred_backend = normalise_backend_preference(
        str((runtime_configuration or {}).get("preferred_backend") or settings.preferred_backend)
    )
    preferred_probe = next((item for item in backends if item.backend == preferred_backend), None)
    if not ffmpeg.discoverable or not ffprobe.discoverable:
        return "failed", "FFmpeg or FFprobe is not available on the worker."
    if scratch["status"] != "healthy":
        return "degraded", "Scratch path is not ready for execution."
    invalid_mapping = next(
        (
            item
            for item in runtime_summary.get("path_mappings", [])
            if item.get("validation_status") not in {None, "usable"}
        ),
        None,
    )
    if invalid_mapping is not None:
        return "degraded", str(invalid_mapping.get("validation_message") or "One or more worker path mappings are invalid.")
    if preferred_backend != "cpu" and preferred_probe is not None and not preferred_probe.usable:
        if settings.allow_cpu_fallback:
            return "degraded", "Preferred hardware backend is unavailable, so this worker will fall back to CPU."
        return "degraded", "Preferred hardware backend is unavailable and CPU fallback is disabled."
    return "healthy", "Remote worker is ready to execute jobs."
