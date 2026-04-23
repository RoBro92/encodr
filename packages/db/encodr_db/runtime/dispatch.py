from __future__ import annotations

from datetime import datetime, timedelta, timezone

from encodr_db.models import Job, Worker, WorkerHealthStatus, WorkerRegistrationStatus, WorkerType
from encodr_shared.scheduling import schedule_windows_allow_now


def job_allows_worker(
    job: Job,
    worker: Worker,
    *,
    now: datetime | None = None,
    preferred_worker: Worker | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if job.pinned_worker_id is not None and job.pinned_worker_id != worker.id:
        return False
    if job.preferred_worker_id and job.preferred_worker_id != worker.id:
        if preferred_worker is not None and worker_is_dispatchable(preferred_worker, now=current):
            return False
    if job.requested_worker_type is not None and job.requested_worker_type != worker.worker_type:
        return False
    if not schedule_windows_allow_now(job.schedule_windows, now=current):
        return False
    if not job.ignore_worker_schedule and not schedule_windows_allow_now(worker.schedule_windows, now=current):
        return False
    return True


def worker_is_dispatchable(
    worker: Worker,
    *,
    now: datetime | None = None,
    heartbeat_grace: timedelta = timedelta(minutes=5),
) -> bool:
    current = now or datetime.now(timezone.utc)
    if not worker.enabled:
        return False
    if worker.worker_type == WorkerType.LOCAL:
        return worker.registration_status != WorkerRegistrationStatus.DISABLED
    if worker.registration_status != WorkerRegistrationStatus.REGISTERED:
        return False
    if worker.last_health_status == WorkerHealthStatus.FAILED:
        return False
    if worker.last_heartbeat_at is None:
        return False
    heartbeat = worker.last_heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    if heartbeat < current - heartbeat_grace:
        return False
    return True
