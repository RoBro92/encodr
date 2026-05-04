from __future__ import annotations

import errno
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import BulkQueueOperation, FileLifecycleState, Job, JobKind, JobStatus, ManualReviewDecisionType, PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.repositories import ManualReviewDecisionRepository, TrackedFileRepository, WorkerRepository
from encodr_db.runtime import WorkerExecutionService
from encodr_core.verification import OutputVerifier
from encodr_shared.scheduling import DAY_ORDER
from encodr_shared.diagnostics import read_log_events
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import FilesystemLayout, create_filesystem_layout
from tests.helpers.jobs import (
    StaticProbeClient,
    StagedRunner,
    create_job,
    create_planned_file,
    media_at_path,
    media_for_plan_output,
    parse_fixture,
)

pytestmark = [pytest.mark.integration]


def test_authenticated_file_list_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Listed Film (2024).mkv", contents="listed")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    response = context.client.get(
        "/api/files",
        params={"lifecycle_state": FileLifecycleState.QUEUED.value, "path_search": "Listed Film"},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["source_filename"] == "Listed Film (2024).mkv"
    assert payload["items"][0]["lifecycle_state"] == FileLifecycleState.QUEUED.value


def test_new_endpoints_reject_unauthenticated_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/files").status_code == 401
    assert context.client.get("/api/jobs").status_code == 401
    assert context.client.get("/api/config/effective").status_code == 401
    assert context.client.post("/api/files/probe", json={"source_path": "/tmp/example.mkv"}).status_code == 401


def test_probe_endpoint_persists_tracked_file_and_probe_snapshot(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Probe Film (2024).mkv", contents="probe")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    response = context.client.post(
        "/api/files/probe",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracked_file"]["source_path"] == source_path.as_posix()
    assert payload["latest_probe_snapshot"]["file_name"] == source_path.name

    with session_factory() as session:
        assert session.query(TrackedFile).count() == 1
        assert session.query(ProbeSnapshot).count() == 1


def test_plan_endpoint_persists_plan_snapshot_and_updates_file_state(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("TV/Example Show/Season 01/Example S01E01.mkv", contents="plan")
    media = media_at_path(parse_fixture("tv_episode.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    response = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    file_id = payload["tracked_file"]["id"]
    assert payload["latest_plan_snapshot"]["action"] == "skip"

    probe_response = context.client.get(
        f"/api/files/{file_id}/probe-snapshots/latest",
        headers=auth.headers,
    )
    plan_response = context.client.get(
        f"/api/files/{file_id}/plan-snapshots/latest",
        headers=auth.headers,
    )
    assert probe_response.status_code == 200
    assert plan_response.status_code == 200

    with session_factory() as session:
        tracked_file = session.get(TrackedFile, file_id)
        assert tracked_file is not None
        assert tracked_file.lifecycle_state == FileLifecycleState.PLANNED
        assert session.query(PlanSnapshot).count() == 1


def test_job_creation_from_latest_plan_works(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Job Film (2024).mkv", contents="job")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)
    plan_response = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )
    file_id = plan_response.json()["tracked_file"]["id"]

    response = context.client.post(
        "/api/jobs",
        json={"tracked_file_id": file_id},
        headers=auth.headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == JobStatus.PENDING.value
    assert payload["tracked_file_id"] == file_id

    list_response = context.client.get("/api/jobs", headers=auth.headers)
    detail_response = context.client.get(f"/api/jobs/{payload['id']}", headers=auth.headers)
    assert list_response.status_code == 200
    assert detail_response.status_code == 200

    with session_factory() as session:
        assert session.query(Job).count() == 1


def test_duplicate_active_job_creation_returns_conflict(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Duplicate Job Film (2024).mkv", contents="job")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)
    file_id = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    ).json()["tracked_file"]["id"]

    first_response = context.client.post("/api/jobs", json={"tracked_file_id": file_id}, headers=auth.headers)
    second_response = context.client.post("/api/jobs", json={"tracked_file_id": file_id}, headers=auth.headers)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert "active job already exists" in second_response.json()["detail"]
    with session_factory() as session:
        assert session.query(Job).count() == 1


def test_retry_endpoint_creates_new_job_record(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Retry Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        session.commit()

    response = context.client.post(
        f"/api/jobs/{persisted.job.id}/retry",
        headers=auth.headers,
    )

    assert response.status_code == 201
    new_job = response.json()
    assert new_job["id"] != persisted.job.id
    assert new_job["status"] == JobStatus.PENDING.value
    assert new_job["attempt_count"] == 2

    with session_factory() as session:
        jobs = session.query(Job).order_by(Job.created_at.asc(), Job.attempt_count.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].status == JobStatus.FAILED
        assert jobs[1].status == JobStatus.PENDING


def test_retry_endpoint_allows_replacement_failure_manual_review_retry(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Replacement Retry Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.MANUAL_REVIEW
        persisted.job.failure_category = "replacement_failed"
        persisted.job.failure_message = "Failed to move the verified output into place."
        session.commit()
        original_job_id = persisted.job.id

    response = context.client.post(
        f"/api/jobs/{original_job_id}/retry",
        headers=auth.headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] != original_job_id
    assert payload["status"] == JobStatus.PENDING.value
    assert payload["attempt_count"] == 2


def test_strip_only_recovery_endpoint_queues_remux_for_size_guard_failure(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Output Growth Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        persisted.job.failure_category = "output_larger_than_input"
        persisted.job.failure_message = "Encoded output is larger than the source file."
        session.commit()
        original_job_id = persisted.job.id

    response = context.client.post(
        f"/api/jobs/{original_job_id}/strip-only-recovery",
        headers=auth.headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] != original_job_id
    assert payload["status"] == JobStatus.PENDING.value
    assert payload["attempt_count"] == 2

    with session_factory() as session:
        jobs = session.query(Job).order_by(Job.created_at.asc(), Job.attempt_count.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].cleared_reason == "Video transcode skipped after failed size/quality guard; audio/subtitle cleanup only."
        assert jobs[1].plan_snapshot.payload["action"] == "remux"
        assert jobs[1].plan_snapshot.payload["video"]["transcode_required"] is False
        assert jobs[1].completed_at is None


def test_retry_endpoint_keeps_protected_replacement_failure_behind_review_gate(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Protected Replacement Retry Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.MANUAL_REVIEW
        persisted.job.failure_category = "replacement_failed"
        persisted.job.failure_message = "Failed to move the verified output into place."
        persisted.job.tracked_file.is_protected = True
        session.commit()
        original_job_id = persisted.job.id

    response = context.client.post(
        f"/api/jobs/{original_job_id}/retry",
        headers=auth.headers,
    )

    assert response.status_code == 409
    assert "requires manual review" in response.json()["detail"]


def test_retry_endpoint_blocks_when_active_job_exists(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Retry Duplicate Film (2024).mkv", contents="retry")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.FAILED
        session.commit()

    first_retry = context.client.post(f"/api/jobs/{persisted.job.id}/retry", headers=auth.headers)
    second_retry = context.client.post(f"/api/jobs/{persisted.job.id}/retry", headers=auth.headers)

    assert first_retry.status_code == 201
    assert second_retry.status_code == 409
    assert "active job already exists" in second_retry.json()["detail"]
    with session_factory() as session:
        assert session.query(Job).count() == 2


def test_cancel_endpoint_marks_pending_job_cancelled_without_execution(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Cancel Film (2024).mkv", contents="cancel")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    response = context.client.post(
        f"/api/jobs/{persisted.job.id}/cancel",
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == JobStatus.CANCELLED.value
    assert payload["failure_category"] == "cancelled_by_operator"
    assert payload["progress_stage"] == "cancelled"
    assert payload["assigned_worker_id"] is None

    with session_factory() as session:
        job = session.get(Job, persisted.job.id)
        tracked_file = session.get(TrackedFile, persisted.job.tracked_file_id)
        assert job is not None
        assert tracked_file is not None
        assert job.status == JobStatus.CANCELLED
        assert job.failure_category == "cancelled_by_operator"
        assert tracked_file.lifecycle_state == FileLifecycleState.PLANNED


def test_job_artwork_endpoint_requires_local_sidecar_and_does_not_fallback_to_frames(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Artwork Film (2024).mkv", contents="artwork")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    missing_response = context.client.get(
        f"/api/jobs/{persisted.job.id}/artwork",
        headers=auth.headers,
    )
    assert missing_response.status_code == 404

    poster_path = source_path.with_name(f"{source_path.stem}-poster.jpg")
    poster_path.write_bytes(b"poster-bytes")

    artwork_response = context.client.get(
        f"/api/jobs/{persisted.job.id}/artwork",
        headers=auth.headers,
    )
    assert artwork_response.status_code == 200
    assert artwork_response.content == b"poster-bytes"


def test_worker_run_once_endpoint_processes_pending_job(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Worker Film (2024).mkv", contents="original")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        output_media = media_for_plan_output(media, persisted.plan)
        session.commit()

    context.app.state.local_worker_loop.execution_service = WorkerExecutionService(
        runner=StagedRunner(output_path=layout.scratch_dir / "api-run-once.mkv"),
        verifier=OutputVerifier(probe_client=StaticProbeClient(output_media)),
    )

    response = context.client.post("/api/worker/run-once", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_job"] is True
    assert payload["final_status"] == "completed"

    with session_factory() as session:
        job = session.query(Job).one()
        assert job.status == JobStatus.COMPLETED
    assert source_path.read_text(encoding="utf-8") == "staged output"


def test_dry_run_jobs_are_created_as_background_analysis_and_processed_by_worker(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Dry Run Film (2024).mkv", contents="dry-run")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)
    monkeypatch.setattr(
        "encodr_db.runtime.worker.FFprobeClient",
        lambda binary_path=None: StaticProbeClient(media),
    )

    create_response = context.client.post(
        "/api/jobs/dry-run",
        json={"selected_paths": [source_path.as_posix()]},
        headers=auth.headers,
    )

    assert create_response.status_code == 201
    create_payload = create_response.json()
    assert create_payload["created_count"] == 1
    assert create_payload["blocked_count"] == 0
    assert create_payload["items"][0]["job"]["job_kind"] == "dry_run"
    job_id = create_payload["items"][0]["job"]["id"]

    run_response = context.client.post("/api/worker/run-once", headers=auth.headers)

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["processed_job"] is True
    assert run_payload["final_status"] == "completed"

    jobs_response = context.client.get(
        "/api/jobs",
        params={"job_kind": "dry_run"},
        headers=auth.headers,
    )
    assert jobs_response.status_code == 200
    listed_job = jobs_response.json()["items"][0]
    assert listed_job["id"] == job_id
    assert listed_job["job_kind"] == "dry_run"
    assert listed_job["analysis_payload"]["planned_action"] in {"skip", "remux", "transcode", "manual_review"}
    assert listed_job["analysis_payload"]["output_filename"]
    assert listed_job["analysis_payload"]["current_size_bytes"] >= 0
    assert "estimated_output_size_bytes" in listed_job["analysis_payload"]
    assert "audio_tracks_removed_count" in listed_job["analysis_payload"]
    assert "subtitle_tracks_removed_count" in listed_job["analysis_payload"]

    with session_factory() as session:
        job = session.query(Job).one()
        assert job.job_kind == JobKind.DRY_RUN
        assert job.status == JobStatus.COMPLETED
        assert isinstance(job.analysis_payload, dict)
        assert job.analysis_payload["source_path"] == source_path.as_posix()
        assert job.output_path is None


def test_dry_run_job_creation_returns_schedule_conflict_for_pinned_worker_outside_window(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Scheduled Dry Run Film (2024).mkv", contents="scheduled")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    next_day = DAY_ORDER[(datetime.now().astimezone().weekday() + 1) % len(DAY_ORDER)]
    schedule_windows = [{"days": [next_day], "start_time": "01:00", "end_time": "02:00"}]

    with session_factory() as session:
        worker = WorkerRepository(session).upsert_local_worker(
            worker_key="worker-local",
            display_name="Local Worker",
            enabled=True,
            preferred_backend="cpu_only",
            allow_cpu_fallback=True,
            max_concurrent_jobs=1,
            schedule_windows=schedule_windows,
            path_mappings=None,
            scratch_path=layout.scratch_dir.as_posix(),
            host_metadata={"hostname": "encodr-host"},
        )
        session.commit()
        worker_id = worker.id

    conflict_response = context.client.post(
        "/api/jobs/dry-run",
        json={
            "selected_paths": [source_path.as_posix()],
            "pinned_worker_id": worker_id,
        },
        headers=auth.headers,
    )

    assert conflict_response.status_code == 409
    conflict_payload = conflict_response.json()["detail"]
    assert conflict_payload["code"] == "worker_schedule_conflict"
    assert conflict_payload["worker_id"] == worker_id
    assert conflict_payload["schedule_summary"]

    override_response = context.client.post(
        "/api/jobs/dry-run",
        json={
            "selected_paths": [source_path.as_posix()],
            "pinned_worker_id": worker_id,
            "ignore_worker_schedule": True,
        },
        headers=auth.headers,
    )

    assert override_response.status_code == 201
    assert override_response.json()["created_count"] == 1


def test_config_effective_endpoint_returns_sanitised_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    response = context.client.get("/api/config/effective", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    payload_text = json.dumps(payload).lower()
    assert payload["policy_version"] >= 1
    assert "profile_names" in payload
    assert "dsn" not in payload_text
    assert "password_hash" not in payload_text
    assert "refresh_token_hash" not in payload_text
    assert "secret_key" not in payload_text
    assert "test-auth-secret-with-sufficient-length" not in payload_text


def test_system_and_worker_status_endpoints_return_useful_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    storage_response = context.client.get("/api/system/storage", headers=auth.headers)
    runtime_response = context.client.get("/api/system/runtime", headers=auth.headers)
    worker_response = context.client.get("/api/worker/status", headers=auth.headers)
    logs_response = context.client.get("/api/system/logs", headers=auth.headers)
    raw_logs_response = context.client.get("/api/system/logs", params={"redact_paths": "false"}, headers=auth.headers)

    assert storage_response.status_code == 200
    assert runtime_response.status_code == 200
    assert worker_response.status_code == 200
    assert logs_response.status_code == 200
    assert raw_logs_response.status_code == 200
    assert storage_response.json()["scratch"]["path"] == layout.scratch_dir.as_posix()
    assert runtime_response.json()["db_reachable"] is True
    assert worker_response.json()["worker_name"] == "worker-local"
    assert worker_response.json()["local_only"] is True
    assert logs_response.json()["log_dir"] == "[PATH]"
    assert raw_logs_response.json()["log_dir"] == (context.bundle.app.data_dir / "logs").as_posix()


def test_invalid_source_path_handling_is_clear_and_safe(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    response = context.client.post(
        "/api/files/probe",
        json={"source_path": (tmp_path / "missing-file.mkv").as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


def test_folder_browse_and_root_selection_workflows_are_constrained_to_media_mounts(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    movies_dir = layout.source_dir / "Movies"
    tv_dir = layout.source_dir / "TV"
    movies_dir.mkdir(parents=True, exist_ok=True)
    tv_dir.mkdir(parents=True, exist_ok=True)
    layout.create_source_file("Movies/Example Film (2024).mkv", contents="film")

    browse_response = context.client.get("/api/files/browse", headers=auth.headers)
    assert browse_response.status_code == 200
    browse_payload = browse_response.json()
    assert browse_payload["root_path"] == layout.source_dir.resolve().as_posix()
    assert {item["name"] for item in browse_payload["entries"]} >= {"Movies", "TV"}

    update_response = context.client.put(
        "/api/config/setup/library-roots",
        json={
            "movies_root": movies_dir.as_posix(),
            "tv_root": tv_dir.as_posix(),
        },
        headers=auth.headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["movies_root"] == movies_dir.resolve().as_posix()
    assert update_response.json()["tv_root"] == tv_dir.resolve().as_posix()

    reject_response = context.client.put(
        "/api/config/setup/library-roots",
        json={"movies_root": tmp_path.as_posix()},
        headers=auth.headers,
    )
    assert reject_response.status_code == 400
    assert "configured media mount" in reject_response.json()["detail"]


def test_processing_rules_can_be_updated_and_are_used_for_planning(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    movies_dir = layout.source_dir / "Movies"
    movies_dir.mkdir(parents=True, exist_ok=True)
    source_path = layout.create_source_file("Movies/Rules Film (2024).mkv", contents="rules")
    media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    roots_response = context.client.put(
        "/api/config/setup/library-roots",
        json={"movies_root": movies_dir.as_posix()},
        headers=auth.headers,
    )
    assert roots_response.status_code == 200

    get_rules_response = context.client.get("/api/config/setup/processing-rules", headers=auth.headers)
    assert get_rules_response.status_code == 200
    assert get_rules_response.json()["movies"]["current"]["target_video_codec"] == "hevc"

    update_rules_response = context.client.put(
        "/api/config/setup/processing-rules",
        json={
            "movies": {
                "target_video_codec": "h264",
                "output_container": "mkv",
                "keep_english_audio_only": True,
                "keep_forced_subtitles": True,
                "keep_one_full_english_subtitle": True,
                "preserve_surround": True,
                "preserve_atmos": True,
                "four_k_mode": "strip_only",
            },
            "tv": None,
        },
        headers=auth.headers,
    )
    assert update_rules_response.status_code == 200
    rules_payload = update_rules_response.json()
    assert rules_payload["movies"]["uses_defaults"] is False
    assert rules_payload["movies"]["current"]["target_video_codec"] == "h264"

    dry_run_response = context.client.post(
        "/api/files/dry-run",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )
    assert dry_run_response.status_code == 200
    dry_run_payload = dry_run_response.json()
    assert dry_run_payload["items"][0]["action"] == "remux"


def test_execution_preferences_can_be_read_and_updated(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    get_response = context.client.get("/api/config/setup/execution-preferences", headers=auth.headers)
    assert get_response.status_code == 200
    assert get_response.json() == {
        "preferred_backend": "cpu_only",
        "allow_cpu_fallback": True,
    }

    update_response = context.client.put(
        "/api/config/setup/execution-preferences",
        json={
            "preferred_backend": "prefer_intel_igpu",
            "allow_cpu_fallback": False,
        },
        headers=auth.headers,
    )
    assert update_response.status_code == 200
    assert update_response.json() == {
        "preferred_backend": "prefer_intel_igpu",
        "allow_cpu_fallback": False,
    }


def test_processing_rules_use_the_most_specific_matching_root(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    tv_root = layout.source_dir / "TV"
    tv_root.mkdir(parents=True, exist_ok=True)
    source_path = layout.create_source_file("TV/Example Show/Season 01/Example Show S01E01.mkv", contents="episode")
    media = media_at_path(parse_fixture("tv_episode.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    roots_response = context.client.put(
        "/api/config/setup/library-roots",
        json={
            "movies_root": layout.source_dir.as_posix(),
            "tv_root": tv_root.as_posix(),
        },
        headers=auth.headers,
    )
    assert roots_response.status_code == 200

    update_rules_response = context.client.put(
        "/api/config/setup/processing-rules",
        json={
            "movies": {
                "target_video_codec": "hevc",
                "output_container": "mp4",
                "keep_english_audio_only": True,
                "keep_forced_subtitles": True,
                "keep_one_full_english_subtitle": True,
                "preserve_surround": True,
                "preserve_atmos": True,
                "four_k_mode": "strip_only",
            },
            "tv": None,
        },
        headers=auth.headers,
    )
    assert update_rules_response.status_code == 200

    plan_response = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )
    assert plan_response.status_code == 200
    assert plan_response.json()["latest_plan_snapshot"]["action"] == "skip"


def test_processing_rules_allow_undetermined_audio_when_english_only_is_disabled(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    movies_dir = layout.source_dir / "Movies"
    movies_dir.mkdir(parents=True, exist_ok=True)
    source_path = layout.create_source_file("Movies/Undetermined Audio Film (2024).mkv", contents="rules")
    base_media = media_at_path(parse_fixture("film_1080p.json"), source_path)
    media = base_media.model_copy(
        update={
            "audio_streams": [
                stream.model_copy(update={"tags": stream.tags.model_copy(update={"language": None})})
                for stream in base_media.audio_streams
            ],
            "has_english_audio": False,
        }
    )
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    roots_response = context.client.put(
        "/api/config/setup/library-roots",
        json={"movies_root": movies_dir.as_posix()},
        headers=auth.headers,
    )
    assert roots_response.status_code == 200

    update_rules_response = context.client.put(
        "/api/config/setup/processing-rules",
        json={
            "movies": {
                "target_video_codec": "hevc",
                "output_container": "mkv",
                "keep_english_audio_only": False,
                "keep_forced_subtitles": True,
                "keep_one_full_english_subtitle": True,
                "preserve_surround": True,
                "preserve_atmos": True,
                "four_k_mode": "strip_only",
            },
            "tv": None,
        },
        headers=auth.headers,
    )
    assert update_rules_response.status_code == 200

    dry_run_response = context.client.post(
        "/api/files/dry-run",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    )
    assert dry_run_response.status_code == 200
    item = dry_run_response.json()["items"][0]
    assert "manual_review_missing_english_audio" not in item["reason_codes"]


def test_scan_and_dry_run_folder_workflows_return_clear_summary_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    episode_path = layout.create_source_file("TV/Example Show/Season 01/Example Show S01E01.mkv", contents="episode")
    film_path = layout.create_source_file("TV/Example Show/Specials/Bonus Feature.mkv", contents="bonus")
    sibling_path = layout.create_source_file("TV4K/Example Show/Season 01/Example Show S01E01.mkv", contents="sibling")
    media = media_at_path(parse_fixture("tv_episode.json"), episode_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)

    scan_response = context.client.post(
        "/api/files/scan",
        json={"source_path": (layout.source_dir / "TV").as_posix()},
        headers=auth.headers,
    )

    assert scan_response.status_code == 200
    scan_payload = scan_response.json()
    assert scan_payload["video_file_count"] == 2
    assert scan_payload["likely_show_count"] == 1
    assert scan_payload["likely_season_count"] == 1
    assert scan_payload["likely_episode_count"] == 1
    assert {item["path"] for item in scan_payload["files"]} == {episode_path.as_posix(), film_path.as_posix()}

    with session_factory() as session:
        TrackedFileRepository(session).upsert_by_path(
            sibling_path,
            last_observed_size=sibling_path.stat().st_size,
        )
        session.commit()

    files_response = context.client.get(
        "/api/files",
        params={"path_prefix": (layout.source_dir / "TV").as_posix(), "limit": 0},
        headers=auth.headers,
    )

    assert files_response.status_code == 200
    files_payload = files_response.json()
    assert files_payload["total"] == 2
    assert files_payload["items"] == []

    listed_files_response = context.client.get(
        "/api/files",
        params={"path_prefix": (layout.source_dir / "TV").as_posix(), "limit": 10},
        headers=auth.headers,
    )

    assert listed_files_response.status_code == 200
    listed_files_payload = listed_files_response.json()
    assert listed_files_payload["total"] == 2
    assert {item["source_path"] for item in listed_files_payload["items"]} == {
        episode_path.as_posix(),
        film_path.as_posix(),
    }

    dry_run_response = context.client.post(
        "/api/files/dry-run",
        json={"folder_path": (layout.source_dir / "TV").as_posix()},
        headers=auth.headers,
    )

    assert dry_run_response.status_code == 200
    dry_run_payload = dry_run_response.json()
    assert dry_run_payload["mode"] == "dry_run"
    assert dry_run_payload["scope"] == "folder"
    assert dry_run_payload["total_files"] == 2
    assert all(item["action"] == "skip" for item in dry_run_payload["items"])

    with session_factory() as session:
        assert session.query(TrackedFile).count() == 3
        assert session.query(ProbeSnapshot).count() == 0
        assert session.query(PlanSnapshot).count() == 0


def test_fresh_setup_state_does_not_auto_register_local_worker(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, _layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    bundle.app.data_dir.mkdir(parents=True, exist_ok=True)
    (bundle.app.data_dir / "setup-state.json").write_text(json.dumps({"setup": "complete"}), encoding="utf-8")

    response = context.client.get("/api/worker/status", headers=auth.headers)

    assert response.status_code == 200
    with session_factory() as session:
        assert WorkerRepository(session).list_workers() == []


def test_folder_browse_uses_the_active_media_root_for_parent_navigation(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    alt_root = tmp_path / "AltMedia"
    nested_folder = alt_root / "TV" / "Example Show"
    nested_folder.mkdir(parents=True, exist_ok=True)
    (nested_folder / "Episode.mkv").write_text("episode", encoding="utf-8")
    bundle.workers.local.media_mounts = [layout.source_dir, alt_root]

    browse_response = context.client.get(
        "/api/files/browse",
        params={"path": nested_folder.as_posix()},
        headers=auth.headers,
    )

    assert browse_response.status_code == 200
    browse_payload = browse_response.json()
    assert browse_payload["root_path"] == alt_root.resolve().as_posix()
    assert browse_payload["parent_path"] == (alt_root / "TV").resolve().as_posix()

    scan_response = context.client.post(
        "/api/files/scan",
        json={"source_path": nested_folder.as_posix()},
        headers=auth.headers,
    )

    assert scan_response.status_code == 200
    assert scan_response.json()["root_path"] == alt_root.resolve().as_posix()


def test_scan_excludes_encodr_backup_and_temp_artifacts(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    media_path = layout.create_source_file("Movies/Processable Film (2024).mkv", contents="film")
    backup_path = layout.create_source_file("Movies/Processable Film (2024).encodr-backup.mkv", contents="backup")
    backup_named_copy_path = layout.create_source_file(
        "Movies/Processable Film (2024).encodr-backup-copy.mkv",
        contents="copy",
    )
    ambiguous_backup_name_path = layout.create_source_file(
        "Movies/Processable Film (2024).encodr-backup.v2.mkv",
        contents="ambiguous",
    )
    temp_path = layout.create_source_file("Movies/Processable Film (2024).tmp.mkv", contents="temp")

    response = context.client.post(
        "/api/files/scan",
        json={"source_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    scanned_paths = {item["path"] for item in payload["files"]}
    assert payload["video_file_count"] == 2
    assert payload["backup_file_count"] == 1
    assert media_path.as_posix() in scanned_paths
    assert backup_named_copy_path.as_posix() in scanned_paths
    assert backup_path.as_posix() not in scanned_paths
    assert ambiguous_backup_name_path.as_posix() not in scanned_paths
    assert temp_path.as_posix() not in scanned_paths

    with session_factory() as session:
        tracked_paths = {item.source_path for item in session.query(TrackedFile).all()}
        assert media_path.as_posix() in tracked_paths
        assert backup_named_copy_path.as_posix() in tracked_paths
        assert backup_path.as_posix() not in tracked_paths
        assert ambiguous_backup_name_path.as_posix() not in tracked_paths
        assert temp_path.as_posix() not in tracked_paths


def test_scan_reconciles_historic_backup_files_into_backup_log(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    media_path = layout.create_source_file("Movies/Historic Film (2024).mkv", contents="replacement")
    backup_path = layout.create_source_file("Movies/Historic Film (2024).encodr-backup.mkv", contents="backup")

    response = context.client.post(
        "/api/files/scan",
        json={"source_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200
    payload = response.json()
    scanned_paths = {item["path"] for item in payload["files"]}
    assert payload["video_file_count"] == 1
    assert payload["backup_file_count"] == 1
    assert media_path.as_posix() in scanned_paths
    assert backup_path.as_posix() not in scanned_paths

    scan_response = context.client.get(f"/api/files/scans/{payload['scan_id']}", headers=auth.headers)
    assert scan_response.status_code == 200
    assert scan_response.json()["backup_file_count"] == 1

    scans_response = context.client.get("/api/files/scans", headers=auth.headers)
    assert scans_response.status_code == 200
    assert scans_response.json()["items"][0]["backup_file_count"] == 1

    backups_response = context.client.get(
        "/api/jobs/backups",
        params={"search": "Historic Film", "limit": 15, "offset": 0},
        headers=auth.headers,
    )

    assert backups_response.status_code == 200
    backups_payload = backups_response.json()
    assert backups_payload["total"] == 1
    assert backups_payload["items"][0]["backup_path"] == backup_path.as_posix()
    assert backups_payload["items"][0]["source_path"] == media_path.as_posix()
    assert backups_payload["items"][0]["backup_policy"] == "discovered"


def test_scan_infers_source_path_from_trailing_backup_marker(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    media_path = layout.create_source_file("Movies/Historic.encodr-backup Cut (2024).mkv", contents="replacement")
    backup_path = layout.create_source_file(
        "Movies/Historic.encodr-backup Cut (2024).encodr-backup.mkv",
        contents="backup",
    )

    response = context.client.post(
        "/api/files/scan",
        json={"source_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 200

    backups_response = context.client.get(
        "/api/jobs/backups",
        params={"search": "Historic", "limit": 15, "offset": 0},
        headers=auth.headers,
    )

    assert backups_response.status_code == 200
    backups_payload = backups_response.json()
    assert backups_payload["total"] == 1
    assert backups_payload["items"][0]["backup_path"] == backup_path.as_posix()
    assert backups_payload["items"][0]["source_path"] == media_path.as_posix()


def test_restore_discovered_backup_returns_file_to_manual_review_with_note(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    current_path = layout.create_source_file("Movies/Restore Film (2024).mkv", contents="replacement")
    backup_path = layout.create_source_file("Movies/Restore Film (2024).encodr-backup.mkv", contents="backup")
    scan_response = context.client.post(
        "/api/files/scan",
        json={"source_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )
    assert scan_response.status_code == 200
    backups_response = context.client.get(
        "/api/jobs/backups",
        params={"search": "Restore Film"},
        headers=auth.headers,
    )
    assert backups_response.status_code == 200
    backup_item = backups_response.json()["items"][0]

    restore_response = context.client.post(
        f"/api/jobs/{backup_item['job_id']}/backup/restore",
        headers=auth.headers,
    )

    assert restore_response.status_code == 200
    assert current_path.read_text(encoding="utf-8") == "backup"
    assert backup_path.exists() is False

    with session_factory() as session:
        tracked_file = session.get(TrackedFile, backup_item["tracked_file_id"])
        assert tracked_file is not None
        assert tracked_file.lifecycle_state == FileLifecycleState.MANUAL_REVIEW
        assert tracked_file.compliance_state.value == "manual_review"
        latest = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(tracked_file.id)
        assert latest is not None
        assert latest.decision_type == ManualReviewDecisionType.HELD
        assert latest.note is not None
        assert "Restored from backup" in latest.note


def test_direct_job_creation_rejects_encodr_backup_target(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    backup_path = layout.create_source_file("Movies/Old Backup.encodr-backup.mkv", contents="backup")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), backup_path)
    with session_factory() as session:
        planned = create_planned_file(session, bundle, media, source_path=backup_path.as_posix())
        session.commit()

    response = context.client.post(
        "/api/jobs",
        json={"plan_snapshot_id": planned.plan_snapshot_id},
        headers=auth.headers,
    )

    assert response.status_code == 409
    assert "backup files" in response.json()["detail"].lower()
    failure_logs = _diagnostic_events(context, "api_job_create_failed")
    assert len(failure_logs) == 1
    assert failure_logs[0].level == "warning"
    assert failure_logs[0].fields["status"] == 409
    assert failure_logs[0].fields["reason"] == response.json()["detail"]
    assert failure_logs[0].fields["exception_type"] == "ApiConflictError"
    assert failure_logs[0].fields["plan_snapshot_id"] == planned.plan_snapshot_id
    with session_factory() as session:
        assert session.query(Job).count() == 0


def test_watched_jobs_ignore_encodr_backup_files(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    watched_dir = layout.source_dir / "Watched"
    watched_dir.mkdir(parents=True, exist_ok=True)
    backup_path = layout.create_source_file("Watched/Show Episode.encodr-backup.mkv", contents="backup")

    create_response = context.client.post(
        "/api/files/watchers",
        json={
            "display_name": "Watched",
            "source_path": watched_dir.as_posix(),
            "media_class": "movie",
            "ruleset_override": None,
            "preferred_worker_id": None,
            "pinned_worker_id": None,
            "preferred_backend": None,
            "schedule_windows": [],
            "auto_queue": True,
            "stage_only": False,
            "enabled": True,
        },
        headers=auth.headers,
    )
    assert create_response.status_code == 201

    summary = context.app.state.orchestration_service.run_once()

    assert summary.scanned_watchers == 1
    assert summary.queued_jobs == 0
    with session_factory() as session:
        assert session.query(Job).count() == 0
        assert session.query(TrackedFile).count() == 0
        scan = context.app.state.orchestration_service.list_recent_scans(session)[0]
        assert scan["files"] == []
    assert backup_path.exists()


def test_batch_plan_and_job_creation_from_folder_persist_results_without_bypassing_review(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    film_path = layout.create_source_file("Movies/Example Film (2024).mkv", contents="film")
    review_path = layout.create_source_file("Movies/Needs Review (2024).mkv", contents="review")

    class MappingProbeClient:
        def __init__(self) -> None:
            self.media_map = {
                film_path.as_posix(): media_at_path(parse_fixture("non4k_remux_languages.json"), film_path),
                review_path.as_posix(): media_at_path(parse_fixture("no_english_audio.json"), review_path),
            }

        def probe_file(self, file_path):  # type: ignore[no-untyped-def]
            return self.media_map[Path(file_path).as_posix()]

    context.app.state.probe_client_factory = lambda: MappingProbeClient()

    plan_response = context.client.post(
        "/api/files/batch-plan",
        json={"folder_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["scope"] == "folder"
    assert plan_payload["total_files"] == 2
    assert {item["latest_plan_snapshot"]["action"] for item in plan_payload["items"]} == {"manual_review", "remux"}

    job_response = context.client.post(
        "/api/jobs/batch",
        json={"folder_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert job_response.status_code == 201
    job_payload = job_response.json()
    assert job_payload["scope"] == "folder"
    assert job_payload["total_files"] == 2
    assert job_payload["created_count"] == 1
    assert job_payload["blocked_count"] == 1
    assert {item["status"] for item in job_payload["items"]} == {"created", "blocked"}

    with session_factory() as session:
        assert session.query(TrackedFile).count() == 2
        assert session.query(PlanSnapshot).count() >= 2
        assert session.query(Job).count() == 1


def test_batch_job_creation_reports_existing_active_job_as_blocked(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source_path = layout.create_source_file("Movies/Batch Duplicate (2024).mkv", contents="film")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.probe_client_factory = lambda: StaticProbeClient(media)
    file_id = context.client.post(
        "/api/files/plan",
        json={"source_path": source_path.as_posix()},
        headers=auth.headers,
    ).json()["tracked_file"]["id"]
    assert context.client.post("/api/jobs", json={"tracked_file_id": file_id}, headers=auth.headers).status_code == 201

    batch_response = context.client.post(
        "/api/jobs/batch",
        json={"folder_path": (layout.source_dir / "Movies").as_posix()},
        headers=auth.headers,
    )

    assert batch_response.status_code == 201
    payload = batch_response.json()
    assert payload["created_count"] == 0
    assert payload["blocked_count"] == 1
    assert payload["items"][0]["status"] == "blocked"
    assert "active job already exists" in payload["items"][0]["message"]
    with session_factory() as session:
        assert session.query(Job).count() == 1


def test_job_list_and_artwork_access_for_100_jobs_keeps_api_healthy(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    with session_factory() as session:
        for index in range(100):
            source_path = layout.create_source_file(f"Movies/Artwork Scale {index:03d} (2024).mkv", contents="film")
            media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
            create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    list_response = context.client.get("/api/jobs", params={"limit": 100}, headers=auth.headers)

    assert list_response.status_code == 200
    job_ids = [item["id"] for item in list_response.json()["items"]]
    assert len(job_ids) == 100
    for job_id in job_ids:
        artwork_response = context.client.get(f"/api/jobs/{job_id}/artwork", headers=auth.headers)
        assert artwork_response.status_code == 404


def test_progress_stream_opens_short_lived_db_sessions(repo_root: Path) -> None:
    source = (repo_root / "apps" / "api" / "app" / "api" / "jobs.py").read_text(encoding="utf-8")
    stream_block = source[source.index("async def stream_job_progress(") : source.index("@router.post(\"/clear-queue\"")]

    assert "session_factory=Depends(get_session_factory)" in stream_block
    assert "current_user: User = Depends(require_admin_user_once)" in stream_block
    assert "session: Session = Depends(get_session)" not in stream_block
    assert "with session_factory() as session:" in stream_block


def test_bulk_queue_processes_500_files_in_batches_and_reports_progress(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    for index in range(500):
        layout.create_source_file(f"Movies/Bulk Film {index:03d} (2024).mkv", contents="film")

    base_media = parse_fixture("non4k_remux_languages.json")
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(base_media)
    counting_factory = CountingSessionFactory(session_factory)
    context.app.state.bulk_queue_service.session_factory = counting_factory

    with session_factory() as session:
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(folder_path=(layout.source_dir / "Movies").as_posix()),
        )
        operation_id = operation.id
        session.commit()

    assert created is True

    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)
        assert operation is not None
        assert operation.status == "completed"
        assert operation.stage == "completed"
        assert operation.batch_size == 25
        assert operation.total_expected == 500
        assert operation.discovered_count == 500
        assert operation.queued_count == 500
        assert operation.skipped_count == 0
        assert operation.blocked_count == 0
        assert operation.failed_count == 0
        assert operation.current_batch == 20
        assert operation.total_batches == 20
        assert session.query(Job).count() == 500

    assert counting_factory.commit_count > 500


def test_bulk_queue_logs_started_completed_and_failed_state_transitions(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("Movies/Logged Bulk Film (2024).mkv", contents="film")
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(
        media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    )

    with session_factory() as session:
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(selected_paths=[source_path.as_posix()]),
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    context.app.state.bulk_queue_service.process_operation(operation_id)

    started_logs = [
        event for event in _diagnostic_events(context, "bulk_queue_operation_started") if event.fields.get("operation_id") == operation_id
    ]
    completed_logs = [
        event for event in _diagnostic_events(context, "bulk_queue_operation_completed") if event.fields.get("operation_id") == operation_id
    ]
    assert len(started_logs) == 1
    assert len(completed_logs) == 1
    assert started_logs[0].fields["operation_id"] == operation_id
    assert started_logs[0].fields["status"] == "running"
    assert completed_logs[0].fields["operation_id"] == operation_id
    assert completed_logs[0].fields["status"] == "completed"
    assert completed_logs[0].fields["duration_ms"] >= 0
    assert completed_logs[0].fields["queued_count"] == 1

    with session_factory() as session:
        failed_operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(selected_paths=[source_path.as_posix(), (layout.source_dir / "Movies" / "Missing.mkv").as_posix()]),
        )
        failed_operation_id = failed_operation.id
        session.commit()

    assert created is True

    def raise_permission_denied(operation_id: str):  # type: ignore[no-untyped-def]
        del operation_id
        raise PermissionError(errno.EACCES, "Permission denied", source_path.as_posix())

    monkeypatch.setattr(context.app.state.bulk_queue_service, "_resolve_selection", raise_permission_denied)

    context.app.state.bulk_queue_service.process_operation(failed_operation_id)

    failed_logs = [
        event
        for event in _diagnostic_events(context, "bulk_queue_operation_failed")
        if event.level == "error" and event.fields.get("operation_id") == failed_operation_id
    ]
    assert len(failed_logs) == 1
    assert failed_logs[0].fields["operation_id"] == failed_operation_id
    assert failed_logs[0].fields["status"] == "failed"
    assert failed_logs[0].fields["exception_type"] == "PermissionError"
    assert failed_logs[0].fields["errno"] == errno.EACCES
    assert "Permission denied" in failed_logs[0].fields["reason"]


def test_bulk_reprocess_selected_processed_file_ignores_existing_backup_file(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("TV/Bluey/Bluey S01E01.mkv", contents="episode")
    backup_path = layout.create_source_file("TV/Bluey/Bluey S01E01.encodr-backup.mkv", contents="backup")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(media)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.COMPLETED
        persisted.job.original_backup_path = backup_path.as_posix()
        session.commit()
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(
                selected_paths=[source_path.as_posix(), backup_path.as_posix()],
                existing_backup_strategy="keep_existing_backup_if_present",
                reprocess_mode="normal",
            ),
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)
        jobs = session.query(Job).order_by(Job.created_at.asc(), Job.attempt_count.asc()).all()
        tracked_paths = {item.source_path for item in session.query(TrackedFile).all()}

        assert operation is not None
        assert operation.status == "completed"
        assert operation.total_expected == 2
        assert operation.queued_count == 1
        assert operation.skipped_count == 1
        assert operation.blocked_count == 0
        assert operation.failed_count == 0
        assert len(jobs) == 2
        assert jobs[-1].status == JobStatus.PENDING
        assert jobs[-1].tracked_file.source_path == source_path.as_posix()
        assert jobs[-1].plan_snapshot.payload["replace"]["existing_backup_strategy"] == "keep_existing_backup"
        assert backup_path.as_posix() not in tracked_paths


def test_bulk_reprocess_existing_backup_record_without_file_creates_new_safe_job(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("TV/Bluey/Bluey S01E01.mkv", contents="episode")
    missing_backup_path = source_path.with_name(f"{source_path.stem}.encodr-backup{source_path.suffix}")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(media)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        persisted.job.status = JobStatus.COMPLETED
        persisted.job.original_backup_path = missing_backup_path.as_posix()
        session.commit()
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(
                selected_paths=[source_path.as_posix()],
                existing_backup_strategy="keep_existing_backup_if_present",
            ),
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    assert not missing_backup_path.exists()
    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)
        new_job = session.query(Job).order_by(Job.created_at.desc()).first()

        assert operation is not None
        assert operation.queued_count == 1
        assert new_job is not None
        assert new_job.plan_snapshot.payload["replace"]["existing_backup_strategy"] == "fail"


def test_bulk_strip_only_reprocess_keeps_video_unchanged_and_reuses_stream_policy(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("TV/Bluey/Bluey S01E02.mkv", contents="episode")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    media.video_streams[0].codec_name = "h264"
    media.video_streams[0].bit_rate = 20_000_000
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(media)

    with session_factory() as session:
        persisted = create_job(session, bundle, media, source_path=source_path.as_posix())
        assert persisted.plan.action.value == "transcode"
        persisted.job.status = JobStatus.COMPLETED
        session.commit()
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(
                selected_paths=[source_path.as_posix()],
                existing_backup_strategy="keep_existing_backup_if_present",
                reprocess_mode="strip_only",
            ),
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)
        new_job = session.query(Job).order_by(Job.created_at.desc()).first()

        assert operation is not None
        assert operation.queued_count == 1
        assert new_job is not None
        assert new_job.status == JobStatus.PENDING
        assert new_job.completed_at is None
        assert new_job.plan_snapshot.payload["action"] == "remux"
        assert new_job.plan_snapshot.payload["video"]["transcode_required"] is False
        assert new_job.plan_snapshot.payload["video"]["handling"] == "preserve"
        assert new_job.plan_snapshot.payload["selected_streams"]["audio_stream_indices"] == persisted.plan.selected_streams.audio_stream_indices
        assert new_job.plan_snapshot.payload["selected_streams"]["subtitle_stream_indices"] == persisted.plan.selected_streams.subtitle_stream_indices
        assert len(new_job.plan_snapshot.payload["selected_streams"]["audio_stream_indices"]) < len(media.audio_streams)
        assert len(new_job.plan_snapshot.payload["selected_streams"]["subtitle_stream_indices"]) < len(media.subtitle_streams)


def test_bulk_reprocess_many_processed_files_uses_bulk_queue_batches(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    media = parse_fixture("non4k_remux_languages.json")
    source_paths = [
        layout.create_source_file(f"TV/Bluey/Bluey S01E{episode:02d}.mkv", contents=f"episode {episode}")
        for episode in range(1, 13)
    ]
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(media)

    with session_factory() as session:
        for source_path in source_paths:
            persisted = create_job(session, bundle, media_at_path(media, source_path), source_path=source_path.as_posix())
            persisted.job.status = JobStatus.COMPLETED
        session.commit()
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(
                selected_paths=[path.as_posix() for path in source_paths],
                reprocess_mode="strip_only",
            ),
            batch_size=5,
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)

        assert operation is not None
        assert operation.status == "completed"
        assert operation.total_expected == 12
        assert operation.queued_count == 12
        assert operation.failed_count == 0
        assert operation.payload["batch_size"] == 5
        assert session.query(Job).count() == 24


def test_bulk_reprocess_blocks_duplicate_active_jobs(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("TV/Bluey/Bluey S01E03.mkv", contents="episode")
    media = media_at_path(parse_fixture("non4k_remux_languages.json"), source_path)
    context.app.state.bulk_queue_service.probe_client_factory = lambda: StaticProbeClient(media)

    with session_factory() as session:
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()
        operation, created = context.app.state.bulk_queue_service.create_operation(
            session,
            payload=bulk_queue_payload(
                selected_paths=[source_path.as_posix()],
                reprocess_mode="strip_only",
            ),
        )
        operation_id = operation.id
        session.commit()

    assert created is True
    context.app.state.bulk_queue_service.process_operation(operation_id)

    with session_factory() as session:
        operation = session.get(BulkQueueOperation, operation_id)
        assert operation is not None
        assert operation.queued_count == 0
        assert operation.blocked_count == 1
        assert operation.result_summary["items"][0]["message"] == "An active job already exists for this tracked file."
        assert session.query(Job).count() == 1


def test_duplicate_bulk_queue_start_reuses_active_operation(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    source_path = layout.create_source_file("Movies/Duplicate Bulk (2024).mkv", contents="film")
    payload = bulk_queue_payload(selected_paths=[source_path.as_posix()])

    with session_factory() as session:
        first, first_created = context.app.state.bulk_queue_service.create_operation(session, payload=payload)
        second, second_created = context.app.state.bulk_queue_service.create_operation(session, payload=payload)
        session.commit()

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    with session_factory() as session:
        assert session.query(BulkQueueOperation).count() == 1
        assert session.query(Job).count() == 0


def test_folder_browse_permission_denied_logs_errno_and_reason(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    denied_folder = layout.source_dir / "Restricted"
    denied_folder.mkdir(parents=True)

    original_iterdir = Path.iterdir

    def permission_denied_iterdir(path: Path):  # type: ignore[no-untyped-def]
        if path == denied_folder.resolve():
            raise PermissionError(errno.EACCES, "Permission denied", path.as_posix())
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", permission_denied_iterdir)

    response = context.client.get(
        "/api/files/browse",
        params={"path": denied_folder.as_posix()},
        headers=auth.headers,
    )

    assert response.status_code == 400
    assert "permission" in response.json()["detail"].lower()
    permission_logs = _diagnostic_events(context, "library_browse_permission_denied")
    assert len(permission_logs) == 1
    assert permission_logs[0].level == "error"
    assert permission_logs[0].fields["errno"] == errno.EACCES
    assert "Permission denied" in permission_logs[0].fields["reason"]


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'api-ops.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )

    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    bundle.app.data_dir = layout.root / "data"
    bundle.workers.local.media_mounts = [layout.source_dir]

    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    return context, session_factory, layout, bundle


def authenticate(context) -> object:
    bootstrap_admin(context.client)
    return login_user(context.client)


def _diagnostic_events(context, event: str):
    return read_log_events(
        context.bundle.app.data_dir / "logs",
        component="api",
        event=event,
        limit=1000,
    )


def bulk_queue_payload(
    *,
    source_path: str | None = None,
    folder_path: str | None = None,
    selected_paths: list[str] | None = None,
    existing_backup_strategy: str = "fail",
    reprocess_mode: str = "normal",
) -> SimpleNamespace:
    return SimpleNamespace(
        source_path=source_path,
        folder_path=folder_path,
        selected_paths=selected_paths or [],
        preferred_worker_id=None,
        pinned_worker_id=None,
        preferred_backend_override=None,
        schedule_windows=[],
        backup_policy="keep",
        existing_backup_strategy=existing_backup_strategy,
        reprocess_mode=reprocess_mode,
    )


class CountingSessionFactory:
    def __init__(self, real_factory) -> None:
        self.real_factory = real_factory
        self.active_sessions = 0
        self.opened_sessions = 0
        self.commit_count = 0

    def __call__(self):
        return CountingSession(self, self.real_factory())


class CountingSession:
    def __init__(self, factory: CountingSessionFactory, session) -> None:
        self.factory = factory
        self.session = session
        self._entered = False

    def __enter__(self):
        self._entered = True
        self.factory.opened_sessions += 1
        self.factory.active_sessions += 1
        self.session.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self.session.__exit__(exc_type, exc, traceback)
        finally:
            if self._entered:
                self.factory.active_sessions -= 1
                self._entered = False

    def __getattr__(self, name: str):
        return getattr(self.session, name)

    def commit(self) -> None:
        self.factory.commit_count += 1
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()
