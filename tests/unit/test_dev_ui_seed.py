from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from encodr_core.planning import ProcessingPlan
from encodr_db.dev_seed_ui import DEMO_MEDIA_ROOT, clear_ui_demo_data, seed_ui_demo_data
from encodr_db.models import FileLifecycleState, Job, JobKind, JobStatus, TrackedFile, WorkerHealthStatus
from encodr_db.repositories import TrackedFileRepository, WorkerRepository
from tests.helpers.db import create_schema_session_factory


def test_dev_ui_seed_replaces_and_clears_demo_records() -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = fake_seed_bundle()

    summary = seed_ui_demo_data(session_factory, bundle)

    assert summary.worker_key == "worker-local"
    assert summary.tracked_files_seeded == 6
    assert summary.jobs_seeded == 3
    assert summary.review_items_seeded == 3

    with session_factory() as session:
        worker = WorkerRepository(session).get_local_worker("worker-local")
        assert worker is not None
        assert worker.display_name == "Demo Local CPU Worker"
        assert worker.preferred_backend == "cpu_only"
        assert worker.allow_cpu_fallback is True

        files = demo_files(session)
        assert len(files) == 6
        assert sum(1 for item in files if item.lifecycle_state == FileLifecycleState.MANUAL_REVIEW) == 3
        for tracked_file in files:
            assert tracked_file.plan_snapshots
            ProcessingPlan.model_validate(tracked_file.plan_snapshots[-1].payload)
        review_candidates = [
            item
            for item in TrackedFileRepository(session).list_review_candidates()
            if item.source_path.startswith(f"{DEMO_MEDIA_ROOT}/")
        ]
        assert len(review_candidates) == 3

        jobs = demo_jobs(session)
        assert len(jobs) == 3
        assert {job.status for job in jobs} == {
            JobStatus.RUNNING,
            JobStatus.SCHEDULED,
            JobStatus.INTERRUPTED,
        }
        assert any(
            job.status == JobStatus.RUNNING
            and job.actual_execution_backend == "cpu"
            and job.progress_stage == "encoding"
            and job.progress_percent == 63
            and job.assigned_worker_id == worker.id
            for job in jobs
        )
        assert any(job.job_kind == JobKind.DRY_RUN and job.status == JobStatus.SCHEDULED for job in jobs)
        assert any(
            job.status == JobStatus.INTERRUPTED
            and job.interruption_retryable is True
            and job.failure_category == "worker_interrupted"
            for job in jobs
        )

    seed_ui_demo_data(session_factory, bundle)
    with session_factory() as session:
        assert len(demo_files(session)) == 6
        assert len(demo_jobs(session)) == 3

    clear_summary = clear_ui_demo_data(session_factory, bundle)

    assert clear_summary.tracked_files_removed == 6
    assert clear_summary.jobs_removed == 3
    assert clear_summary.review_items_removed == 3
    assert clear_summary.worker_removed is True

    with session_factory() as session:
        assert demo_files(session) == []
        assert demo_jobs(session) == []
        assert WorkerRepository(session).get_local_worker("worker-local") is None


def test_dev_ui_seed_restores_existing_local_worker_settings() -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = fake_seed_bundle()

    with session_factory() as session:
        worker = WorkerRepository(session).upsert_local_worker(
            worker_key="worker-local",
            display_name="Real Local Worker",
            enabled=True,
            preferred_backend="prefer_intel_igpu",
            allow_cpu_fallback=False,
            max_concurrent_jobs=2,
            schedule_windows=[{"days": ["sat"], "start_time": "01:00", "end_time": "05:00"}],
            path_mappings=[{"label": "Media", "server_path": "/media", "worker_path": "/mnt/media"}],
            scratch_path="/real-scratch",
            host_metadata={"hostname": "real-host"},
        )
        worker.last_health_status = WorkerHealthStatus.DEGRADED
        worker.last_health_summary = "Real worker warning."
        session.commit()

    seed_ui_demo_data(session_factory, bundle)
    clear_ui_demo_data(session_factory, bundle)

    with session_factory() as session:
        worker = WorkerRepository(session).get_local_worker("worker-local")
        assert worker is not None
        assert worker.display_name == "Real Local Worker"
        assert worker.preferred_backend == "prefer_intel_igpu"
        assert worker.allow_cpu_fallback is False
        assert worker.max_concurrent_jobs == 2
        assert worker.schedule_windows == [{"days": ["sat"], "start_time": "01:00", "end_time": "05:00"}]
        assert worker.path_mappings == [{"label": "Media", "server_path": "/media", "worker_path": "/mnt/media"}]
        assert worker.scratch_path == "/real-scratch"
        assert worker.host_metadata == {"hostname": "real-host"}
        assert worker.last_health_status == WorkerHealthStatus.DEGRADED
        assert worker.last_health_summary == "Real worker warning."


def demo_files(session):
    return list(
        session.scalars(
            select(TrackedFile).where(TrackedFile.source_path.startswith(f"{DEMO_MEDIA_ROOT}/"))
        )
    )


def demo_jobs(session):
    return list(
        session.scalars(
            select(Job)
            .join(TrackedFile)
            .where(TrackedFile.source_path.startswith(f"{DEMO_MEDIA_ROOT}/"))
        )
    )


def fake_seed_bundle():
    return SimpleNamespace(
        workers=SimpleNamespace(
            local=SimpleNamespace(
                id="worker-local",
                host="lxc-main",
                queue="local",
                scratch_dir=Path("/temp"),
                media_mounts=[Path("/media")],
            )
        )
    )
