from __future__ import annotations

import platform

from app.config import WorkerAgentSettings
from app.version import read_agent_version
from encodr_shared.worker_runtime import probe_binary, probe_directory, probe_execution_backends


def build_capability_summary(settings: WorkerAgentSettings) -> dict[str, object]:
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

    return {
        "execution_modes": execution_modes,
        "supported_video_codecs": [],
        "supported_audio_codecs": [],
        "hardware_hints": hardware_hints,
        "binary_support": {"ffmpeg": ffmpeg.discoverable, "ffprobe": ffprobe.discoverable},
        "max_concurrent_jobs": 1,
        "tags": ["remote", settings.queue],
    }


def build_host_summary() -> dict[str, object]:
    return {
        "hostname": platform.node() or None,
        "platform": platform.platform(),
        "agent_version": read_agent_version(),
        "python_version": platform.python_version(),
    }


def build_runtime_summary(settings: WorkerAgentSettings) -> dict[str, object]:
    return {
        "queue": settings.queue,
        "scratch_dir": settings.scratch_dir,
        "media_mounts": list(settings.media_mounts),
        "last_completed_job_id": None,
    }


def build_binary_summary(settings: WorkerAgentSettings) -> list[dict[str, object]]:
    ffmpeg = probe_binary(settings.ffmpeg_path)
    ffprobe = probe_binary(settings.ffprobe_path)
    return [
        {
            "name": "ffmpeg",
            "configured_path": ffmpeg.configured_path,
            "discoverable": ffmpeg.discoverable,
            "message": ffmpeg.message,
        },
        {
            "name": "ffprobe",
            "configured_path": ffprobe.configured_path,
            "discoverable": ffprobe.discoverable,
            "message": ffprobe.message,
        },
    ]


def build_worker_health(settings: WorkerAgentSettings) -> tuple[str, str]:
    ffmpeg = probe_binary(settings.ffmpeg_path)
    ffprobe = probe_binary(settings.ffprobe_path)
    scratch = probe_directory(settings.scratch_dir or ".", writable_required=True)
    if not ffmpeg.discoverable or not ffprobe.discoverable:
        return "failed", "FFmpeg or FFprobe is not available on the worker."
    if scratch["status"] != "healthy":
        return "degraded", "Scratch path is not ready for execution."
    return "healthy", "Remote worker is ready to execute jobs."
