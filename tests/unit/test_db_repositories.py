from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from encodr_core.config import load_config_bundle
from encodr_core.planning import PlanAction, build_processing_plan
from encodr_core.probe import parse_ffprobe_json_output
from encodr_db import Base
from encodr_db.models import ComplianceState, FileLifecycleState, JobStatus
from encodr_db.repositories import JobRepository, PlanSnapshotRepository, ProbeSnapshotRepository, TrackedFileRepository

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


def database_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def parse_fixture(name: str):
    return parse_ffprobe_json_output((FIXTURES_DIR / name).read_text(encoding="utf-8"), file_path=FIXTURES_DIR / name)
