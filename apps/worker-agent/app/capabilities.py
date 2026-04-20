from __future__ import annotations

import platform

from app.config import WorkerAgentSettings


def build_capability_summary(settings: WorkerAgentSettings) -> dict[str, object]:
    hardware_hints: list[str] = ["cpu_only"]
    worker_key_lower = settings.worker_key.lower()
    display_name_lower = settings.display_name.lower()
    if "intel" in worker_key_lower or "intel" in display_name_lower:
        hardware_hints = ["intel_qsv"]
    elif "amd" in worker_key_lower or "amd" in display_name_lower:
        hardware_hints = ["amd_gpu"]

    return {
        "execution_modes": ["remux", "transcode"],
        "supported_video_codecs": ["hevc"],
        "supported_audio_codecs": [],
        "hardware_hints": hardware_hints,
        "binary_support": {"ffmpeg": True, "ffprobe": True},
        "max_concurrent_jobs": 1,
        "tags": ["remote", settings.queue],
    }


def build_host_summary() -> dict[str, object]:
    return {
        "hostname": platform.node() or None,
        "platform": platform.platform(),
        "agent_version": "0.1.0",
        "python_version": platform.python_version(),
    }


def build_runtime_summary(settings: WorkerAgentSettings) -> dict[str, object]:
    return {
        "queue": settings.queue,
        "scratch_dir": settings.scratch_dir,
        "media_mounts": list(settings.media_mounts),
        "last_completed_job_id": None,
    }


def build_binary_summary() -> list[dict[str, object]]:
    return [
        {"name": "ffmpeg", "configured_path": None, "discoverable": None, "message": "Discovery deferred to future agent execution milestones."},
        {"name": "ffprobe", "configured_path": None, "discoverable": None, "message": "Discovery deferred to future agent execution milestones."},
    ]
