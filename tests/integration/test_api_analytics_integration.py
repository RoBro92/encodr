from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import JobStatus, ReplacementStatus, VerificationStatus
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import create_job, media_at_path, parse_fixture

pytestmark = [pytest.mark.integration]


def test_analytics_overview_endpoint_returns_expected_aggregate_structure(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_analytics_history(session_factory, layout, bundle)

    response = context.client.get("/api/analytics/overview", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tracked_files"] == 2
    assert payload["processed_file_count"] == 1
    assert payload["average_processed_per_day"] == 1
    assert any(item["value"] == "completed" for item in payload["jobs_by_status"])
    assert payload["protected_file_count"] == 1
    assert payload["four_k_file_count"] == 1


def test_analytics_storage_endpoint_returns_measured_savings(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_analytics_history(session_factory, layout, bundle)

    response = context.client.get("/api/analytics/storage", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_space_saved_bytes"] == 800
    assert payload["average_space_saved_per_day_bytes"] == 600
    assert payload["measurable_completed_job_count"] == 1
    assert any(item["action"] == "remux" and item["space_saved_bytes"] == 600 for item in payload["savings_by_action"])


def test_analytics_outcomes_endpoint_returns_status_and_failure_breakdown(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_analytics_history(session_factory, layout, bundle)

    response = context.client.get("/api/analytics/outcomes", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert any(item["value"] == "completed" for item in payload["jobs_by_status"])
    assert any(item["value"] == "passed" for item in payload["verification_outcomes"])
    assert payload["top_failure_categories"][0]["category"] == "verification_failed"
    assert len(payload["recent_outcomes"]) >= 2


def test_analytics_media_endpoint_returns_supported_media_summaries(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_analytics_history(session_factory, layout, bundle)

    response = context.client.get("/api/analytics/media", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_probe_count"] == 2
    assert payload["latest_plan_count"] == 2
    assert payload["total_audio_tracks_removed"] == 1
    assert payload["total_subtitle_tracks_removed"] == 2
    assert payload["latest_probe_english_audio_count"] >= 1
    assert any(item["resolution"] == "4K" for item in payload["action_breakdown_by_resolution"])


def test_analytics_recent_endpoint_returns_recent_completed_and_failed_items(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)
    seed_analytics_history(session_factory, layout, bundle)

    response = context.client.get("/api/analytics/recent", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["recent_completed_jobs"]) == 1
    assert len(payload["recent_failed_jobs"]) == 1


def test_analytics_endpoints_reject_unauthenticated_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/analytics/overview").status_code == 401
    assert context.client.get("/api/analytics/dashboard").status_code == 401


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'api-analytics.sqlite').as_posix()}"
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


def seed_analytics_history(session_factory, layout, bundle) -> None:
    with session_factory() as session:
        remux_source = layout.create_source_file("Movies/Analytics Film (2024).mkv", contents="analytics")
        remux_media = media_at_path(parse_fixture("non4k_remux_languages.json"), remux_source)
        remux_context = create_job(session, bundle, remux_media, source_path=remux_source.as_posix())
        remux_context.job.status = JobStatus.COMPLETED
        remux_context.job.completed_at = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
        remux_context.job.verification_status = VerificationStatus.PASSED
        remux_context.job.replacement_status = ReplacementStatus.SUCCEEDED
        remux_context.job.input_size_bytes = 1000
        remux_context.job.output_size_bytes = 400
        remux_context.job.space_saved_bytes = 600
        remux_context.job.analysis_payload = {
            "audio_tracks_removed_count": 1,
            "subtitle_tracks_removed_count": 2,
        }
        remux_context.job.tracked_file.lifecycle_state = remux_context.job.tracked_file.lifecycle_state.COMPLETED
        remux_context.job.tracked_file.is_protected = False

        four_k_source = layout.create_source_file("Movies/Analytics 4K Film (2024).mkv", contents="fourk")
        four_k_media = media_at_path(parse_fixture("film_4k_hdr_dv.json"), four_k_source)
        four_k_context = create_job(session, bundle, four_k_media, source_path=four_k_source.as_posix())
        four_k_context.job.status = JobStatus.FAILED
        four_k_context.job.failure_category = "verification_failed"
        four_k_context.job.failure_message = "The output probe data did not match the expected video codec."
        four_k_context.job.verification_status = VerificationStatus.FAILED
        four_k_context.job.replacement_status = ReplacementStatus.NOT_REQUIRED
        four_k_context.job.input_size_bytes = 2000
        four_k_context.job.output_size_bytes = 1800
        four_k_context.job.space_saved_bytes = 200
        four_k_context.job.tracked_file.is_protected = True

        session.commit()
