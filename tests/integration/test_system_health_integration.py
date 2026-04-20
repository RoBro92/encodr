from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import Job, JobStatus
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import create_job, media_at_path, parse_fixture

pytestmark = [pytest.mark.integration]


def test_worker_status_endpoint_returns_enriched_health_data(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_job_health(session_factory, bundle, layout)

    response = context.client.get("/api/worker/status", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["worker_name"] == "worker-local"
    assert payload["mode"] == "single-node-local"
    assert payload["ffmpeg"]["status"] == "healthy"
    assert payload["ffprobe"]["status"] == "healthy"
    assert payload["queue_health"]["pending_count"] == 1
    assert payload["queue_health"]["failed_count"] == 1
    assert payload["queue_health"]["manual_review_count"] == 1
    assert payload["queue_health"]["status"] == "degraded"
    assert payload["self_test_available"] is True


def test_storage_endpoint_returns_path_health_structure_and_degraded_status(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_mount = tmp_path / "missing-media"
    context, _, _, _ = build_context(
        tmp_path,
        repo_root,
        monkeypatch,
        extra_media_mounts=[missing_mount],
    )
    auth = authenticate(context)

    response = context.client.get("/api/system/storage", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["standard_media_root"] == "/media"
    assert any(item["status"] == "failed" for item in payload["media_mounts"])
    assert any(item["issue_code"] == "path_missing" for item in payload["media_mounts"])
    assert payload["summary"] == "Storage is not configured yet."
    assert any("media mount not found at" in warning.lower() for warning in payload["warnings"])


def test_runtime_endpoint_returns_health_summary_and_queue_state(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_job_health(session_factory, bundle, layout)

    response = context.client.get("/api/system/runtime", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["db_reachable"] is True
    assert payload["schema_reachable"] is True
    assert payload["auth_enabled"] is True
    assert payload["standard_media_root"] == "/media"
    assert payload["local_worker_enabled"] is True
    assert payload["user_count"] == 1
    assert payload["queue_health"]["pending_count"] == 1
    assert payload["queue_health"]["manual_review_count"] == 1


def test_worker_self_test_endpoint_returns_structured_result(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    response = context.client.post("/api/worker/self-test", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert len(payload["checks"]) >= 4
    assert all("status" in check for check in payload["checks"])


def test_health_endpoints_reject_unauthenticated_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/worker/status").status_code == 401
    assert context.client.get("/api/system/storage").status_code == 401
    assert context.client.get("/api/system/runtime").status_code == 401
    assert context.client.post("/api/worker/self-test").status_code == 401


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_media_mounts: list[Path] | None = None,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'system-health.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )

    ffmpeg_path = create_fake_binary(tmp_path / "bin" / "ffmpeg")
    ffprobe_path = create_fake_binary(tmp_path / "bin" / "ffprobe")

    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    bundle.app.data_dir = layout.root / "data"
    bundle.app.data_dir.mkdir(parents=True, exist_ok=True)
    bundle.app.media.ffmpeg_path = ffmpeg_path
    bundle.app.media.ffprobe_path = ffprobe_path
    bundle.workers.local.media_mounts = [layout.source_dir, *(extra_media_mounts or [])]

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


def create_fake_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def seed_job_health(session_factory, bundle, layout) -> None:
    with session_factory() as session:
        pending_source = layout.create_source_file("Movies/Pending Film (2024).mkv", contents="pending")
        pending_media = media_at_path(parse_fixture("film_1080p.json"), pending_source)
        pending_context = create_job(session, bundle, pending_media, source_path=pending_source.as_posix())
        pending_context.job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)

        failed_source = layout.create_source_file("Movies/Failed Film (2024).mkv", contents="failed")
        failed_media = media_at_path(parse_fixture("non4k_remux_languages.json"), failed_source)
        failed_context = create_job(session, bundle, failed_media, source_path=failed_source.as_posix())
        failed_context.job.status = JobStatus.FAILED
        failed_context.job.failure_message = "Verification failed."
        failed_context.job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)

        manual_source = layout.create_source_file("Movies/Review Film (2024).mkv", contents="review")
        manual_media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), manual_source)
        manual_context = create_job(session, bundle, manual_media, source_path=manual_source.as_posix())
        manual_context.job.status = JobStatus.MANUAL_REVIEW
        manual_context.job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=45)

        completed_source = layout.create_source_file("Movies/Completed Film (2024).mkv", contents="done")
        completed_media = media_at_path(parse_fixture("tv_episode.json"), completed_source)
        completed_context = create_job(session, bundle, completed_media, source_path=completed_source.as_posix())
        completed_context.job.status = JobStatus.COMPLETED
        completed_context.job.completed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        completed_context.job.updated_at = completed_context.job.completed_at

        running_source = layout.create_source_file("Movies/Running Film (2024).mkv", contents="running")
        running_media = media_at_path(parse_fixture("film_1080p.json"), running_source)
        running_context = create_job(session, bundle, running_media, source_path=running_source.as_posix())
        running_context.job.status = JobStatus.RUNNING
        running_context.job.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        session.commit()
