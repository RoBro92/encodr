from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from encodr_core.config import load_config_bundle
from encodr_db import Base
from encodr_db.models import ManualReviewDecisionType, User, UserRole
from encodr_db.repositories import ManualReviewDecisionRepository, ProbeSnapshotRepository, TrackedFileRepository
from tests.helpers.jobs import create_job, create_planned_file, parse_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manual_review_decision_persistence_and_latest_lookup() -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        user = create_user(session)
        media = parse_fixture("ambiguous_forced_subtitle.json")
        context = create_planned_file(session, bundle, media, source_path=media.file_path.as_posix())

        repository = ManualReviewDecisionRepository(session)
        first = repository.add_decision(
            tracked_file_id=context.tracked_file_id,
            created_by_user=user,
            decision_type=ManualReviewDecisionType.HELD,
            plan_snapshot_id=context.plan_snapshot_id,
            note="Needs a second look.",
        )
        second = repository.add_decision(
            tracked_file_id=context.tracked_file_id,
            created_by_user=user,
            decision_type=ManualReviewDecisionType.APPROVED,
            plan_snapshot_id=context.plan_snapshot_id,
            note="Approved after checking the subtitles.",
        )

        latest = repository.get_latest_for_tracked_file(context.tracked_file_id)
        assert first.id != second.id
        assert latest is not None
        assert latest.id == second.id
        assert latest.created_by_user.username == "admin"


def test_review_candidate_derivation_includes_manual_review_protected_and_failed_jobs() -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        tracked_files = TrackedFileRepository(session)

        manual_media = parse_fixture("ambiguous_forced_subtitle.json")
        manual_context = create_planned_file(session, bundle, manual_media, source_path=manual_media.file_path.as_posix())

        protected_media = parse_fixture("film_4k_hdr_dv.json")
        protected_context = create_planned_file(session, bundle, protected_media, source_path=protected_media.file_path.as_posix())

        failed_media = parse_fixture("film_1080p.json")
        failed_context = create_job(session, bundle, failed_media, source_path=failed_media.file_path.as_posix())
        failed_context.job.status = failed_context.job.status.FAILED
        failed_context.job.failure_message = "Verification failed."
        session.flush()

        candidate_ids = {item.id for item in tracked_files.list_review_candidates()}
        assert manual_context.tracked_file_id in candidate_ids
        assert protected_context.tracked_file_id in candidate_ids
        assert failed_context.job.tracked_file_id in candidate_ids


def test_operator_protected_updates_are_persisted_without_clearing_planner_protection() -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)
        user = create_user(session)
        tracked_files = TrackedFileRepository(session)

        media = parse_fixture("film_4k_hdr_dv.json")
        context = create_planned_file(session, bundle, media, source_path=media.file_path.as_posix())
        tracked_file = tracked_files.get_by_id(context.tracked_file_id)
        assert tracked_file is not None
        assert tracked_file.is_protected is True

        tracked_files.set_operator_protected(
            tracked_file,
            value=True,
            note="Operator hold for protected file.",
            user_id=user.id,
            updated_at=datetime.now(timezone.utc),
        )
        assert tracked_file.operator_protected is True
        assert tracked_file.operator_protected_note == "Operator hold for protected file."

        tracked_files.set_operator_protected(
            tracked_file,
            value=False,
            note="Operator hold cleared.",
            user_id=user.id,
            updated_at=datetime.now(timezone.utc),
        )
        assert tracked_file.operator_protected is False
        assert tracked_file.is_protected is True


def database_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def create_user(session: Session) -> User:
    user = User(
        username="admin",
        password_hash="hashed",
        role=UserRole.ADMIN,
        is_active=True,
        is_bootstrap_admin=True,
    )
    session.add(user)
    session.flush()
    return user
