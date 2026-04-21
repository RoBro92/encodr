from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkerAgentSettings:
    api_base_url: str
    worker_key: str
    display_name: str
    registration_secret: str | None
    worker_token: str | None
    worker_token_file: Path | None
    heartbeat_interval_seconds: int
    queue: str
    scratch_dir: str | None
    media_mounts: tuple[str, ...]
    ffmpeg_path: str
    ffprobe_path: str


def load_settings(environ: dict[str, str] | None = None) -> WorkerAgentSettings:
    env = environ or os.environ
    token_file = env.get("ENCODR_WORKER_AGENT_TOKEN_FILE")
    api_base_url = env.get("ENCODR_WORKER_AGENT_API_BASE_URL", "http://localhost:8000/api").rstrip("/")
    worker_key = env.get("ENCODR_WORKER_AGENT_KEY", "worker-remote").strip()
    display_name = env.get("ENCODR_WORKER_AGENT_DISPLAY_NAME", env.get("ENCODR_WORKER_AGENT_KEY", "worker-remote")).strip()
    heartbeat_interval = int(env.get("ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS", "60"))

    if not api_base_url:
        raise ValueError("ENCODR_WORKER_AGENT_API_BASE_URL must not be empty.")
    if not worker_key:
        raise ValueError("ENCODR_WORKER_AGENT_KEY must not be empty.")
    if not display_name:
        raise ValueError("ENCODR_WORKER_AGENT_DISPLAY_NAME must not be empty.")
    if heartbeat_interval < 1:
        raise ValueError("ENCODR_WORKER_AGENT_HEARTBEAT_INTERVAL_SECONDS must be greater than zero.")

    return WorkerAgentSettings(
        api_base_url=api_base_url,
        worker_key=worker_key,
        display_name=display_name,
        registration_secret=env.get("ENCODR_WORKER_AGENT_REGISTRATION_SECRET") or env.get("ENCODR_WORKER_REGISTRATION_SECRET"),
        worker_token=env.get("ENCODR_WORKER_AGENT_TOKEN"),
        worker_token_file=Path(token_file) if token_file else None,
        heartbeat_interval_seconds=heartbeat_interval,
        queue=env.get("ENCODR_WORKER_AGENT_QUEUE", "remote-default"),
        scratch_dir=env.get("ENCODR_WORKER_AGENT_SCRATCH_DIR"),
        media_mounts=tuple(
            value.strip()
            for value in env.get("ENCODR_WORKER_AGENT_MEDIA_MOUNTS", "").split(",")
            if value.strip()
        ),
        ffmpeg_path=env.get("ENCODR_WORKER_AGENT_FFMPEG_PATH", "ffmpeg"),
        ffprobe_path=env.get("ENCODR_WORKER_AGENT_FFPROBE_PATH", "ffprobe"),
    )
