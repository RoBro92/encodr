from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BinaryStatusResponse(BaseModel):
    configured_path: str
    discoverable: bool
    exists: bool
    executable: bool


class WorkerRunOnceResponse(BaseModel):
    processed_job: bool
    job_id: str | None = None
    final_status: str | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkerStatusResponse(BaseModel):
    worker_name: str
    local_only: bool
    default_queue: str
    ffmpeg: BinaryStatusResponse
    ffprobe: BinaryStatusResponse
    local_worker_enabled: bool
    local_worker_queue: str
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_processed_job_id: str | None = None
    last_result_status: str | None = None
    last_failure_message: str | None = None
    processed_jobs: int = 0
    capabilities: dict[str, bool]
