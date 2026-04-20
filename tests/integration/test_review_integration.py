from __future__ import annotations

from pathlib import Path

import pytest

from encodr_core.config import load_config_bundle
from encodr_db.models import AuditEventType, JobStatus, ManualReviewDecisionType
from encodr_db.repositories import AuditEventRepository, JobRepository, ManualReviewDecisionRepository, TrackedFileRepository
from tests.helpers.api import create_test_api_context
from tests.helpers.auth import bootstrap_admin, login_user
from tests.helpers.db import create_migrated_session_factory
from tests.helpers.filesystem import create_filesystem_layout
from tests.helpers.jobs import StaticProbeClient, create_job, create_planned_file, media_at_path, parse_fixture

pytestmark = [pytest.mark.integration]


def test_review_items_endpoint_returns_open_manual_review_and_protected_items(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    manual_source = layout.create_source_file("Movies/Review Film (2024).mkv", contents="review")
    manual_media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), manual_source)
    protected_source = layout.create_source_file("Movies/Protected Film (2024).mkv", contents="protected")
    protected_media = media_at_path(parse_fixture("film_4k_hdr_dv.json"), protected_source)

    with session_factory() as session:
        create_planned_file(session, context.bundle, manual_media, source_path=manual_source.as_posix())
        create_planned_file(session, context.bundle, protected_media, source_path=protected_source.as_posix())
        session.commit()

    response = context.client.get("/api/review/items", headers=auth.headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert any(item["tracked_file"]["source_filename"] == "Review Film (2024).mkv" for item in payload["items"])
    assert any(item["protected_state"]["is_protected"] is True for item in payload["items"])


def test_approve_decision_persists_and_is_audited(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source = layout.create_source_file("Movies/Approve Film (2024).mkv", contents="review")
    media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), source)
    with session_factory() as session:
        planned = create_planned_file(session, context.bundle, media, source_path=source.as_posix())
        session.commit()

    response = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/approve",
        headers=auth.headers,
        json={"note": "Approved after manual inspection."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["decision_type"] == "approved"
    assert payload["review_item"]["review_status"] == "approved"

    with session_factory() as session:
        latest = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(planned.tracked_file_id)
        events = AuditEventRepository(session).list_events(limit=5)
        assert latest is not None
        assert latest.decision_type == ManualReviewDecisionType.APPROVED
        assert any(event.event_type == AuditEventType.MANUAL_REVIEW_ACTION for event in events)


def test_reject_and_hold_decisions_persist_correctly(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    reject_source = layout.create_source_file("Movies/Reject Film (2024).mkv", contents="review")
    reject_media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), reject_source)
    hold_source = layout.create_source_file("Movies/Hold Film (2024).mkv", contents="review")
    hold_media = media_at_path(parse_fixture("no_english_audio.json"), hold_source)

    with session_factory() as session:
        reject_context = create_planned_file(session, context.bundle, reject_media, source_path=reject_source.as_posix())
        hold_context = create_planned_file(session, context.bundle, hold_media, source_path=hold_source.as_posix())
        session.commit()

    reject_response = context.client.post(
        f"/api/review/items/{reject_context.tracked_file_id}/reject",
        headers=auth.headers,
        json={"note": "Rejected for now."},
    )
    hold_response = context.client.post(
        f"/api/review/items/{hold_context.tracked_file_id}/hold",
        headers=auth.headers,
        json={"note": "Hold until source is replaced."},
    )

    assert reject_response.status_code == 200
    assert hold_response.status_code == 200
    assert reject_response.json()["review_item"]["review_status"] == "rejected"
    assert hold_response.json()["review_item"]["review_status"] == "held"


def test_mark_protected_and_clear_protected_update_state_safely(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source = layout.create_source_file("Movies/Operator Protected Film (2024).mkv", contents="review")
    media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), source)
    with session_factory() as session:
        planned = create_planned_file(session, context.bundle, media, source_path=source.as_posix())
        session.commit()

    mark_response = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/mark-protected",
        headers=auth.headers,
        json={"note": "Do not process automatically."},
    )
    clear_response = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/clear-protected",
        headers=auth.headers,
        json={"note": "Protection cleared after review."},
    )

    assert mark_response.status_code == 200
    assert mark_response.json()["review_item"]["protected_state"]["operator_protected"] is True
    assert clear_response.status_code == 200
    assert clear_response.json()["review_item"]["protected_state"]["operator_protected"] is False


def test_create_job_from_approved_review_item_is_append_only(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source = layout.create_source_file("Movies/Approved Job Film (2024).mkv", contents="review")
    media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), source)
    with session_factory() as session:
        planned = create_planned_file(session, context.bundle, media, source_path=source.as_posix())
        session.commit()

    approve = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/approve",
        headers=auth.headers,
        json={"note": "Approved for job creation."},
    )
    assert approve.status_code == 200

    create_job_response = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/create-job",
        headers=auth.headers,
        json={"note": "Queue the approved file."},
    )

    assert create_job_response.status_code == 201
    payload = create_job_response.json()
    assert payload["job"]["status"] == "pending"
    assert payload["review_item"]["review_status"] == "resolved"

    with session_factory() as session:
        jobs = JobRepository(session).list_jobs(tracked_file_id=planned.tracked_file_id)
        decisions = ManualReviewDecisionRepository(session).list_for_tracked_file(planned.tracked_file_id)
        assert len(jobs) == 1
        assert decisions[0].decision_type == ManualReviewDecisionType.JOB_CREATED
        assert decisions[1].decision_type == ManualReviewDecisionType.APPROVED


def test_review_endpoints_reject_unauthenticated_access(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, _, _ = build_context(tmp_path, repo_root, monkeypatch)

    assert context.client.get("/api/review/items").status_code == 401
    assert context.client.post("/api/review/items/example/approve", json={"note": "nope"}).status_code == 401


def test_invalid_review_actions_are_rejected_clearly(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source = layout.create_source_file("Movies/Blocked Job Film (2024).mkv", contents="review")
    media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), source)
    protected_source = layout.create_source_file("Movies/Planner Protected Film (2024).mkv", contents="review")
    protected_media = media_at_path(parse_fixture("film_4k_hdr_dv.json"), protected_source)
    with session_factory() as session:
        planned = create_planned_file(session, context.bundle, media, source_path=source.as_posix())
        protected_planned = create_planned_file(session, context.bundle, protected_media, source_path=protected_source.as_posix())
        session.commit()

    job_response = context.client.post(
        f"/api/review/items/{planned.tracked_file_id}/create-job",
        headers=auth.headers,
        json={"note": "Attempt without approval."},
    )
    clear_response = context.client.post(
        f"/api/review/items/{protected_planned.tracked_file_id}/clear-protected",
        headers=auth.headers,
        json={"note": "Attempt to clear planner protection."},
    )

    assert job_response.status_code == 409
    assert "approved" in job_response.json()["detail"].lower()
    assert clear_response.status_code == 409
    assert "operator-applied protection" in clear_response.json()["detail"].lower()


def test_file_and_job_detail_models_reflect_review_and_protected_state(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, session_factory, layout, _bundle = build_context(tmp_path, repo_root, monkeypatch)
    auth = authenticate(context)

    source = layout.create_source_file("Movies/Detail Review Film (2024).mkv", contents="review")
    media = media_at_path(parse_fixture("ambiguous_forced_subtitle.json"), source)
    with session_factory() as session:
        job_context = create_job(session, context.bundle, media, source_path=source.as_posix())
        job_context.job.status = JobStatus.MANUAL_REVIEW
        session.commit()

    file_response = context.client.get(f"/api/files/{job_context.job.tracked_file_id}", headers=auth.headers)
    job_response = context.client.get(f"/api/jobs/{job_context.job.id}", headers=auth.headers)

    assert file_response.status_code == 200
    assert file_response.json()["requires_review"] is True
    assert file_response.json()["review_status"] == "open"
    assert job_response.status_code == 200
    assert job_response.json()["requires_review"] is True
    assert job_response.json()["review_status"] == "open"


def build_context(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    layout = create_filesystem_layout(tmp_path)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'review.sqlite').as_posix()}"
    _, session_factory = create_migrated_session_factory(
        repo_root=repo_root,
        database_url=database_url,
    )
    bundle = load_config_bundle(project_root=repo_root)
    bundle.app.scratch_dir = layout.scratch_dir
    bundle.app.data_dir = layout.root / "data"
    bundle.app.data_dir.mkdir(parents=True, exist_ok=True)
    bundle.workers.local.media_mounts = [layout.source_dir]

    monkeypatch.setenv("ENCODR_AUTH_SECRET", "test-auth-secret-with-sufficient-length")
    context = create_test_api_context(
        repo_root=repo_root,
        session_factory=session_factory,
        bundle=bundle,
    )
    context.app.state.probe_client_factory = lambda: StaticProbeClient(parse_fixture("film_1080p.json"))
    return context, session_factory, layout, bundle


def authenticate(context) -> object:
    bootstrap_admin(context.client)
    return login_user(context.client)
