from __future__ import annotations

from datetime import datetime, timedelta, timezone

from encodr_db.models import Job, JobStatus, Worker, WorkerHealthStatus, WorkerRegistrationStatus, WorkerType
from encodr_db.runtime.dispatch import job_allows_worker, worker_is_dispatchable


def test_job_allows_only_the_pinned_worker() -> None:
    now = datetime.now(timezone.utc)
    pinned = build_worker("worker-pinned", now=now)
    other = build_worker("worker-other", now=now)
    job = Job(
        tracked_file_id="tracked-1",
        plan_snapshot_id="plan-1",
        status=JobStatus.PENDING,
        pinned_worker_id="worker-pinned",
    )

    assert job_allows_worker(job, pinned, now=now) is True
    assert job_allows_worker(job, other, now=now) is False


def test_job_prefers_specific_worker_only_while_it_is_dispatchable() -> None:
    now = datetime.now(timezone.utc)
    preferred = build_worker("worker-preferred", now=now)
    fallback = build_worker("worker-fallback", now=now)
    job = Job(
        tracked_file_id="tracked-1",
        plan_snapshot_id="plan-1",
        status=JobStatus.PENDING,
        preferred_worker_id="worker-preferred",
    )

    assert job_allows_worker(job, preferred, now=now, preferred_worker=preferred) is True
    assert job_allows_worker(job, fallback, now=now, preferred_worker=preferred) is False

    preferred.last_heartbeat_at = now - timedelta(minutes=15)
    assert worker_is_dispatchable(preferred, now=now) is False
    assert job_allows_worker(job, fallback, now=now, preferred_worker=preferred) is True


def build_worker(worker_id: str, *, now: datetime) -> Worker:
    return Worker(
        id=worker_id,
        worker_key=worker_id,
        display_name=worker_id,
        worker_type=WorkerType.REMOTE,
        enabled=True,
        registration_status=WorkerRegistrationStatus.REGISTERED,
        preferred_backend="cpu_only",
        allow_cpu_fallback=True,
        last_health_status=WorkerHealthStatus.HEALTHY,
        last_heartbeat_at=now,
    )
