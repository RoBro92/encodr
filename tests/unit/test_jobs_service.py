from __future__ import annotations

from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import JobStatus
from tests.helpers.api import import_api_module
from tests.helpers.db import create_schema_session_factory
from tests.helpers.jobs import create_job, media_at_path, parse_fixture


def test_restore_backup_checks_conflicts_before_moving_replacement(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Restore Film.mkv"
    replacement_path = tmp_path / "Restore Film.mp4"
    restored_replacement_path = tmp_path / "Restore Film.encodr-restored-replacement.mp4"
    backup_path = tmp_path / "Restore Film.encodr-backup.mkv"
    source_path.write_text("occupied source", encoding="utf-8")
    replacement_path.write_text("replacement", encoding="utf-8")
    backup_path.write_text("backup", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.COMPLETED
        persisted.job.final_output_path = replacement_path.as_posix()
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            with pytest.raises(jobs_module.ApiConflictError) as error:
                jobs_module.JobsService().restore_backup(session, job_id=persisted.job.id)

    assert "original path is occupied" in str(error.value)
    assert source_path.read_text(encoding="utf-8") == "occupied source"
    assert replacement_path.read_text(encoding="utf-8") == "replacement"
    assert backup_path.read_text(encoding="utf-8") == "backup"
    assert restored_replacement_path.exists() is False


def test_restore_backup_keeps_replacement_when_backup_rename_fails(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Restore Film.mkv"
    replacement_path = tmp_path / "Restore Film.mp4"
    backup_path = tmp_path / "Restore Film.encodr-backup.mkv"
    replacement_path.write_text("replacement", encoding="utf-8")
    backup_path.write_text("backup", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    original_rename = Path.rename

    def failing_backup_rename(path: Path, target: Path) -> Path:
        if path == backup_path:
            raise OSError("rename failed")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", failing_backup_rename)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.COMPLETED
        persisted.job.final_output_path = replacement_path.as_posix()
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            with pytest.raises(OSError):
                jobs_module.JobsService().restore_backup(session, job_id=persisted.job.id)

    assert source_path.exists() is False
    assert replacement_path.read_text(encoding="utf-8") == "replacement"
    assert backup_path.read_text(encoding="utf-8") == "backup"


def test_strip_only_review_plan_preserves_output_growth_guard(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Animated Episode.mkv"
    source_path.write_text("source", encoding="utf-8")
    media = media_at_path(parse_fixture("tv_episode.json"), source_path)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.plan.video.output_larger_than_input_review_percent = 7
        with import_api_module("app.services.review") as review_module:
            strip_plan = review_module.ReviewService._strip_only_plan(persisted.plan)

    assert strip_plan.video.transcode_required is False
    assert strip_plan.video.max_allowed_video_reduction_percent is None
    assert strip_plan.video.output_larger_than_input_review_percent == 7


def test_retry_job_can_set_existing_backup_strategy(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Backup Collision.mkv"
    backup_path = tmp_path / "Backup Collision.encodr-backup.mkv"
    source_path.write_text("source", encoding="utf-8")
    backup_path.write_text("backup", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        persisted.job.failure_category = "replacement_failed"
        persisted.job.failure_message = "A backup file already exists for the source path."
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            retry_job = jobs_module.JobsService().retry_job(
                session,
                job_id=persisted.job.id,
                existing_backup_strategy="replace_backup",
            )

        assert retry_job.attempt_count == persisted.job.attempt_count + 1
        assert retry_job.plan_snapshot_id != persisted.job.plan_snapshot_id
        assert retry_job.plan_snapshot.payload["replace"]["existing_backup_strategy"] == "replace_backup"


def test_retry_job_rejects_backup_strategy_for_other_failures(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Worker Failure.mkv"
    backup_path = tmp_path / "Worker Failure.encodr-backup.mkv"
    source_path.write_text("source", encoding="utf-8")
    backup_path.write_text("backup", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        persisted.job.failure_category = "worker_failed"
        persisted.job.failure_message = "The worker stopped unexpectedly."
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            with pytest.raises(jobs_module.ApiConflictError) as error:
                jobs_module.JobsService().retry_job(
                    session,
                    job_id=persisted.job.id,
                    existing_backup_strategy="replace_backup",
                )

        assert "failed because a backup already exists" in str(error.value)


def test_retry_job_rejects_backup_strategy_when_recorded_backup_is_missing(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    source_path = tmp_path / "Missing Backup.mkv"
    backup_path = tmp_path / "Missing Backup.encodr-backup.mkv"
    source_path.write_text("source", encoding="utf-8")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        persisted.job.failure_category = "replacement_failed"
        persisted.job.failure_message = "A backup file already exists for the source path."
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            with pytest.raises(jobs_module.ApiConflictError) as error:
                jobs_module.JobsService().retry_job(
                    session,
                    job_id=persisted.job.id,
                    existing_backup_strategy="keep_existing_backup",
                )

        assert "backup file is no longer available" in str(error.value)


def test_resolve_problem_jobs_can_retry_matching_failures(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    first_media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Retry Film One.mkv")
    second_media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Retry Film Two.mkv")
    first_media.file_path.write_text("source one", encoding="utf-8")
    second_media.file_path.write_text("source two", encoding="utf-8")

    with session_factory() as session:
        first = create_job(session, bundle, first_media, source_path=first_media.file_path.as_posix()).job
        first.status = JobStatus.FAILED
        first.failure_category = "replacement_failed"
        first.failure_message = "A backup file already exists for the source path."
        second = create_job(session, bundle, second_media, source_path=second_media.file_path.as_posix()).job
        second.status = JobStatus.CANCELLED
        second.failure_category = "replacement_failed"
        second.failure_message = "A backup file already exists for the source path."
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            retried = jobs_module.JobsService().resolve_problem_jobs(
                session,
                job_ids=[first.id, second.id],
                action="retry",
            )

        assert [job.status for job in retried] == [JobStatus.PENDING, JobStatus.PENDING]
        assert {job.tracked_file_id for job in retried} == {first.tracked_file_id, second.tracked_file_id}
        assert all(job.attempt_count == 2 for job in retried)


def test_resolve_problem_jobs_marks_matching_failures_skipped(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Skip Film.mkv")
    media.file_path.write_text("source", encoding="utf-8")

    with session_factory() as session:
        first = create_job(session, bundle, media, source_path=media.file_path.as_posix()).job
        first.status = JobStatus.FAILED
        first.failure_category = "replacement_failed"
        first.failure_message = "A backup file already exists for the source path."
        second = create_job(session, bundle, media, source_path=media.file_path.as_posix()).job
        second.status = JobStatus.CANCELLED
        second.failure_category = "replacement_failed"
        second.failure_message = "A backup file already exists for the source path."
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            skipped = jobs_module.JobsService().resolve_problem_jobs(
                session,
                job_ids=[first.id, second.id],
                action="skip",
            )

        assert [job.status for job in skipped] == [JobStatus.SKIPPED, JobStatus.SKIPPED]
        assert all(job.failure_category == "operator_skipped" for job in skipped)
        assert all(job.progress_percent == 100 for job in skipped)


def test_resolve_problem_jobs_rejects_mixed_errors(tmp_path: Path, repo_root: Path) -> None:
    _engine, session_factory = create_schema_session_factory()
    bundle = load_config_bundle(project_root=repo_root)
    media = media_at_path(parse_fixture("film_1080p.json"), tmp_path / "Mixed Film.mkv")
    media.file_path.write_text("source", encoding="utf-8")

    with session_factory() as session:
        backup = create_job(session, bundle, media, source_path=media.file_path.as_posix()).job
        backup.status = JobStatus.FAILED
        backup.failure_category = "replacement_failed"
        backup.failure_message = "A backup file already exists for the source path."
        worker = create_job(session, bundle, media, source_path=media.file_path.as_posix()).job
        worker.status = JobStatus.FAILED
        worker.failure_category = "worker_failed"
        worker.failure_message = "The worker stopped unexpectedly."
        session.commit()

        with import_api_module("app.services.jobs") as jobs_module:
            with pytest.raises(jobs_module.ApiConflictError) as error:
                jobs_module.JobsService().resolve_problem_jobs(
                    session,
                    job_ids=[backup.id, worker.id],
                    action="skip",
                )

        assert "same error" in str(error.value)
