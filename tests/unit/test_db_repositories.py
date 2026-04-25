from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from encodr_core.config import load_config_bundle
from encodr_core.execution import ExecutionResult
from encodr_core.planning import PlanAction, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_shared.scheduling import schedule_windows_allow_now
from encodr_db import Base
from encodr_db.models import (
    ComplianceState,
    FileLifecycleState,
    JobStatus,
    Worker,
    WorkerHealthStatus,
    WorkerRegistrationStatus,
    WorkerType,
)
from encodr_db.repositories import (
    JobRepository,
    PlanSnapshotRepository,
    ProbeSnapshotRepository,
    ScanRecordRepository,
    TrackedFileRepository,
    WatchedJobRepository,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tracked_file_upsert() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        media = parse_fixture("tv_episode.json")

        record = tracked_files.upsert_by_path(media.file_path, media_file=media)
        updated = tracked_files.upsert_by_path(media.file_path, media_file=media)

        assert record.id == updated.id
        assert updated.source_filename == "Example Show - s01e01 - Pilot.mkv"
        assert updated.is_4k is False


def test_multiple_probe_snapshots_are_preserved() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        media = parse_fixture("tv_episode.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        first = probes.add_probe_snapshot(tracked_file, media, schema_version=1)
        second = probes.add_probe_snapshot(tracked_file, media, schema_version=2)

        latest = tracked_files.get_latest_probe_snapshot(tracked_file.id)
        assert first.id != second.id
        assert latest is not None
        assert latest.schema_version == 2


def test_plan_snapshots_link_correctly() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("film_1080p.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(media, bundle, source_path=media.file_path)
        plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)

        latest = tracked_files.get_latest_plan_snapshot(tracked_file.id)
        assert plan_snapshot.tracked_file_id == tracked_file.id
        assert plan_snapshot.probe_snapshot_id == probe_snapshot.id
        assert latest is not None
        assert latest.id == plan_snapshot.id


def test_job_creation_from_plan_snapshot() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        jobs = JobRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("film_4k_hdr_dv.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(media, bundle, source_path=media.file_path)
        plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        job = jobs.create_job_from_plan(tracked_file, plan_snapshot, worker_name="worker-local")

        assert job.status == JobStatus.PENDING
        assert job.worker_name == "worker-local"
        assert job.replace_in_place is True
        assert job.require_verification is True


def test_job_creation_starts_scheduled_when_outside_window() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        jobs = JobRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("film_1080p.json")
        now = datetime.now(timezone.utc)
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        current_day = days[now.weekday()]
        next_day = next(day for day in days if day != current_day)
        schedule_windows = [
            {
                "days": [next_day],
                "start_time": "00:00",
                "end_time": "23:59",
            }
        ]

        assert schedule_windows_allow_now(schedule_windows, now=now) is False

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(media, bundle, source_path=media.file_path)
        plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        job = jobs.create_job_from_plan(
            tracked_file,
            plan_snapshot,
            schedule_windows=schedule_windows,
        )

        assert job.status == JobStatus.SCHEDULED
        assert job.scheduled_for_at is not None
        assert job.schedule_summary


def test_file_state_updates_from_plan_result() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("film_4k_hdr_dv.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(media, bundle, source_path=media.file_path)
        plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        tracked_files.update_file_state_from_plan_result(tracked_file, plan)

        assert tracked_file.lifecycle_state == FileLifecycleState.PLANNED
        assert tracked_file.compliance_state == ComplianceState.NON_COMPLIANT
        assert tracked_file.last_processed_policy_version == plan.policy_context.policy_version
        assert tracked_file.is_protected is True


def test_already_processed_under_policy() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("tv_episode.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(
            media,
            bundle,
            source_path="/media/TV/Example Show/Season 01/Example Show - s01e01 - Pilot.mkv",
        )
        plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        tracked_files.update_file_state_from_plan_result(tracked_file, plan)

        assert (
            tracked_files.already_processed_under_policy(
                media.file_path,
                plan.policy_context.policy_version,
                profile_name=plan.policy_context.selected_profile_name,
            )
            is True
        )
        assert tracked_files.already_processed_under_policy(media.file_path, 999) is False


def test_basic_file_and_job_filtering() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        jobs = JobRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)

        first_media = parse_fixture("tv_episode.json")
        second_media = parse_fixture("film_4k_hdr_dv.json")

        first_file = tracked_files.upsert_by_path(first_media.file_path, media_file=first_media)
        first_probe = probes.add_probe_snapshot(first_file, first_media)
        first_plan = build_processing_plan(
            first_media,
            bundle,
            source_path="/media/TV/Example Show/Season 01/Example Show - s01e01 - Pilot.mkv",
        )
        first_plan_snapshot = plans.add_plan_snapshot(first_file, first_probe, first_plan)
        tracked_files.update_file_state_from_plan_result(first_file, first_plan)
        jobs.create_job_from_plan(first_file, first_plan_snapshot)

        second_file = tracked_files.upsert_by_path(second_media.file_path, media_file=second_media)
        second_probe = probes.add_probe_snapshot(second_file, second_media)
        second_plan = build_processing_plan(second_media, bundle, source_path=second_media.file_path)
        second_plan_snapshot = plans.add_plan_snapshot(second_file, second_probe, second_plan)
        tracked_files.update_file_state_from_plan_result(second_file, second_plan)
        jobs.create_job_from_plan(second_file, second_plan_snapshot)

        compliant_files = tracked_files.list_files(compliance_state=ComplianceState.COMPLIANT)
        protected_files = tracked_files.list_files(protected_only=True)
        pending_jobs = jobs.list_jobs(status=JobStatus.PENDING)

        assert [item.id for item in compliant_files] == [first_file.id]
        assert [item.id for item in protected_files] == [second_file.id]
        assert len(pending_jobs) == 2


def test_scan_records_are_listed_newest_first() -> None:
    with database_session() as session:
        scans = ScanRecordRepository(session)
        older = scans.add_scan_record(
            source_path="/media/Movies",
            root_path="/media",
            source_kind="manual",
            watched_job_id=None,
            directory_count=1,
            direct_directory_count=1,
            video_file_count=1,
            likely_show_count=0,
            likely_season_count=0,
            likely_episode_count=0,
            likely_film_count=1,
            files_payload=[{"path": "/media/Movies/Old.mkv"}],
            scanned_at=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
        )
        newer = scans.add_scan_record(
            source_path="/media/Movies/New",
            root_path="/media",
            source_kind="watched",
            watched_job_id="watch-1",
            directory_count=2,
            direct_directory_count=1,
            video_file_count=2,
            likely_show_count=0,
            likely_season_count=0,
            likely_episode_count=0,
            likely_film_count=2,
            files_payload=[{"path": "/media/Movies/New/New.mkv"}],
            scanned_at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
        )

        recent = scans.list_recent()
        reopened = scans.get_by_id(older.id)

        assert [item.id for item in recent[:2]] == [newer.id, older.id]
        assert reopened is not None
        assert reopened.files_payload[0]["path"] == "/media/Movies/Old.mkv"


def test_watched_job_state_tracks_last_scan_and_known_paths() -> None:
    with database_session() as session:
        watched_jobs = WatchedJobRepository(session)
        watched = watched_jobs.create_or_update(
            watched_job_id=None,
            display_name="SSD ingest",
            source_path="/ssd/downloads",
            media_class="movie",
            ruleset_override="movies",
            preferred_worker_id=None,
            pinned_worker_id=None,
            preferred_backend="cpu_only",
            schedule_windows=[],
            auto_queue=True,
            stage_only=False,
            enabled=True,
        )

        scanned_at = datetime(2026, 4, 22, 12, 30, tzinfo=timezone.utc)
        updated = watched_jobs.update_last_scan(
            watched,
            last_scan_record_id="scan-1",
            last_seen_paths=["/ssd/downloads/Film One (2024).mkv"],
            scanned_at=scanned_at,
            enqueue_at=scanned_at,
        )

        assert updated.last_scan_record_id == "scan-1"
        assert updated.last_seen_paths == ["/ssd/downloads/Film One (2024).mkv"]
        assert updated.last_scan_at == scanned_at
        assert updated.last_enqueue_at == scanned_at


def test_interrupted_jobs_clear_assignment_and_stop_counting_as_active() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        jobs = JobRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("tv_episode.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(
            media,
            bundle,
            source_path="/media/TV/Example Show/Season 01/Example Show - s01e01 - Pilot.mkv",
        )
        plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        job = jobs.create_job_from_plan(tracked_file, plan_snapshot)
        worker = Worker(
            worker_key="remote-1",
            display_name="Remote 1",
            worker_type=WorkerType.REMOTE,
            enabled=True,
            registration_status=WorkerRegistrationStatus.REGISTERED,
            preferred_backend="cpu_only",
            allow_cpu_fallback=True,
            last_health_status=WorkerHealthStatus.HEALTHY,
        )
        session.add(worker)
        session.flush()
        jobs.assign_worker(job, worker=worker)

        assert jobs.has_active_job_for_tracked_file(tracked_file.id) is True

        interrupted = jobs.mark_interrupted(
            job,
            interrupted_at=datetime(2026, 4, 22, 13, 0, tzinfo=timezone.utc),
            reason="Worker stopped responding.",
        )

        assert interrupted.status == JobStatus.INTERRUPTED
        assert interrupted.assigned_worker_id is None
        assert interrupted.interruption_retryable is True
        assert interrupted.interruption_reason == "Worker stopped responding."
        assert jobs.has_active_job_for_tracked_file(tracked_file.id) is False


def test_failed_execution_gets_one_automatic_retry_then_manual_review() -> None:
    with database_session() as session:
        tracked_files = TrackedFileRepository(session)
        probes = ProbeSnapshotRepository(session)
        plans = PlanSnapshotRepository(session)
        jobs = JobRepository(session)
        bundle = load_config_bundle(project_root=REPO_ROOT)
        media = parse_fixture("film_1080p.json")

        tracked_file = tracked_files.upsert_by_path(media.file_path, media_file=media)
        probe_snapshot = probes.add_probe_snapshot(tracked_file, media)
        plan = build_processing_plan(media, bundle, source_path=media.file_path)
        plan_snapshot = plans.add_plan_snapshot(tracked_file, probe_snapshot, plan)
        first_job = jobs.create_job_from_plan(tracked_file, plan_snapshot)
        failed_at = datetime(2026, 4, 22, 13, 0, tzinfo=timezone.utc)

        first_result = ExecutionResult(
            mode="failed",
            status="failed",
            command=[],
            output_path=None,
            failure_message="ffmpeg failed.",
            failure_category="execution_failed",
            started_at=failed_at,
            completed_at=failed_at,
        )
        jobs.mark_result(first_job, first_result)
        tracked_files.update_file_state_from_execution_result(tracked_file, plan, first_result)
        retry_job = jobs.apply_automatic_retry_policy(first_job, first_result)

        assert retry_job is not None
        assert first_job.status == JobStatus.FAILED
        assert retry_job.status == JobStatus.PENDING
        assert retry_job.attempt_count == 2
        assert tracked_file.lifecycle_state == FileLifecycleState.QUEUED
        assert tracked_file.id not in {item.id for item in tracked_files.list_review_candidates()}

        second_result = ExecutionResult(
            mode="failed",
            status="failed",
            command=[],
            output_path=None,
            failure_message="Retry failed.",
            failure_category="execution_failed",
            started_at=failed_at,
            completed_at=failed_at,
        )
        jobs.mark_result(retry_job, second_result)
        tracked_files.update_file_state_from_execution_result(tracked_file, plan, second_result)
        final_retry = jobs.apply_automatic_retry_policy(retry_job, second_result)

        assert final_retry is None
        assert retry_job.status == JobStatus.MANUAL_REVIEW
        assert tracked_file.lifecycle_state == FileLifecycleState.MANUAL_REVIEW
        assert tracked_file.id in {item.id for item in tracked_files.list_review_candidates()}


def database_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def parse_fixture(name: str):
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)
