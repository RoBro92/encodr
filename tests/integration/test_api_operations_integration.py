from __future__ import annotations

import json
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import FileLifecycleState, Job, JobStatus, PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.runtime import WorkerExecutionService
from encodr_core.verification import OutputVerifier
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import FilesystemLayout, create_filesystem_layout
from tests.helpers.jobs import StaticProbeClient, StagedRunner, create_job, media_at_path, parse_fixture

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
        jobs = session.query(Job).order_by(Job.created_at.asc()).all()
        assert len(jobs) == 2
        assert jobs[0].status == JobStatus.FAILED
        assert jobs[1].status == JobStatus.PENDING


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
        create_job(session, bundle, media, source_path=source_path.as_posix())
        session.commit()

    context.app.state.local_worker_loop.execution_service = WorkerExecutionService(
        runner=StagedRunner(output_path=layout.scratch_dir / "api-run-once.mkv"),
        verifier=OutputVerifier(probe_client=StaticProbeClient(media)),
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

    assert storage_response.status_code == 200
    assert runtime_response.status_code == 200
    assert worker_response.status_code == 200
    assert storage_response.json()["scratch"]["path"] == layout.scratch_dir.as_posix()
    assert runtime_response.json()["db_reachable"] is True
    assert worker_response.json()["worker_name"] == "worker-local"
    assert worker_response.json()["local_only"] is True


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
        assert session.query(TrackedFile).count() == 0
        assert session.query(ProbeSnapshot).count() == 0
        assert session.query(PlanSnapshot).count() == 0


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
