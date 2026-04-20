from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from encodr_core.config import load_config_bundle
from encodr_core.planning import PlanAction
from encodr_db import Base
from encodr_db.models import JobStatus, PlanSnapshot, ReplacementStatus, VerificationStatus
from encodr_db.repositories import AnalyticsRepository
from tests.helpers.jobs import create_job, parse_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_analytics_repository_summaries_are_derived_from_persisted_rows() -> None:
    with database_session() as session:
        bundle = load_config_bundle(project_root=REPO_ROOT)

        first_context = create_job(
            session,
            bundle,
            parse_fixture("non4k_remux_languages.json"),
            source_path="/media/Movies/Analytics One (2024).mkv",
        )
        first_context.job.status = JobStatus.COMPLETED
        first_context.job.input_size_bytes = 1_000
        first_context.job.output_size_bytes = 700
        first_context.job.space_saved_bytes = 300
        first_context.job.verification_status = VerificationStatus.PASSED
        first_context.job.replacement_status = ReplacementStatus.SUCCEEDED

        second_context = create_job(
            session,
            bundle,
            parse_fixture("film_1080p.json"),
            source_path="/media/Movies/Analytics Two (2024).mkv",
        )
        second_plan_snapshot = (
            session.query(PlanSnapshot)
            .filter_by(tracked_file_id=second_context.job.tracked_file_id)
            .order_by(PlanSnapshot.created_at.desc())
            .first()
        )
        assert second_plan_snapshot is not None
        second_plan_snapshot.action = PlanAction.TRANSCODE
        second_context.job.status = JobStatus.FAILED
        second_context.job.failure_category = "verification_failed"
        second_context.job.failure_message = "Required subtitle intent is present in the output."
        second_context.job.input_size_bytes = 2_000
        second_context.job.output_size_bytes = 1_200
        second_context.job.space_saved_bytes = 800
        second_context.job.verification_status = VerificationStatus.FAILED
        second_context.job.replacement_status = ReplacementStatus.NOT_REQUIRED

        session.commit()

        repository = AnalyticsRepository(session)
        assert repository.count_tracked_files() == 2
        assert repository.count_jobs_by_status()["completed"] == 1
        assert repository.count_jobs_by_status()["failed"] == 1
        assert repository.count_plans_by_action()["remux"] == 1
        assert repository.count_plans_by_action()["transcode"] == 1

        storage = repository.summarise_storage_outcomes()
        assert storage.total_original_size_bytes == 3_000
        assert storage.total_output_size_bytes == 1_900
        assert storage.total_space_saved_bytes == 1_100
        assert storage.measurable_job_count == 2
        assert storage.measurable_completed_job_count == 1
        assert storage.savings_by_action["remux"]["space_saved_bytes"] == 300

        failures = repository.top_failure_categories()
        assert failures == [
            {
                "category": "verification_failed",
                "count": 1,
                "sample_message": "Required subtitle intent is present in the output.",
            }
        ]


def database_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)
