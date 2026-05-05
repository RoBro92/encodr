from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.helpers.api import import_api_module


pytestmark = [pytest.mark.unit]


def test_batch_job_endpoint_accumulates_targets_before_creation(repo_root: Path) -> None:
    source = (repo_root / "apps" / "api" / "app" / "api" / "jobs.py").read_text(encoding="utf-8")
    batch_block = source[source.index("def create_batch_jobs(") : source.index("@router.post(\"/dry-run\"")]

    assert "planned_targets.append((source_file.as_posix(), tracked_file, plan_snapshot))" in batch_block
    assert batch_block.count("jobs_service.create_batch_jobs(") == 1
    assert "planned_targets=[(source_file.as_posix(), tracked_file, plan_snapshot)]" not in batch_block


def test_dry_run_job_endpoint_uses_precomputed_config_lookup(repo_root: Path) -> None:
    source = (repo_root / "apps" / "api" / "app" / "api" / "jobs.py").read_text(encoding="utf-8")
    dry_run_block = source[source.index("def create_dry_run_jobs(") :]

    assert "config_payloads_by_source_path" in dry_run_block
    assert "next(\n                    config_payload" not in dry_run_block


def test_active_job_uniqueness_migration_guards_existing_duplicates(repo_root: Path) -> None:
    migration = (
        repo_root
        / "packages"
        / "db"
        / "encodr_db"
        / "migrations"
        / "versions"
        / "20260429_0018_active_job_uniqueness.py"
    ).read_text(encoding="utf-8")

    assert "HAVING COUNT(*) > 1" in migration
    assert "RuntimeError" in migration
    assert "UPDATE jobs" not in migration
    assert "DELETE FROM jobs" not in migration


def test_schedule_window_rejects_malformed_time() -> None:
    with import_api_module("app.schemas.schedules") as schedules:
        with pytest.raises(ValidationError):
            schedules.ScheduleWindowRequest(days=["mon"], start_time="xx:yy", end_time="12:00")

        with pytest.raises(ValidationError):
            schedules.ScheduleWindowRequest(days=["mon"], start_time="23:00", end_time="24:00")


def test_bulk_queue_operation_response_defaults_missing_count_fields() -> None:
    with import_api_module("app.schemas.jobs") as jobs:
        response = jobs.BulkQueueOperationResponse(
            id="bulk-1",
            scope="folder",
            status="completed",
            stage="completed",
            batch_size=25,
            total_expected=2,
            discovered_count=2,
            current_batch=1,
            total_batches=1,
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        )

    assert response.queued_count == 0
    assert response.skipped_count == 0
    assert response.blocked_count == 0
    assert response.failed_count == 0


def test_bulk_queue_operation_response_logs_missing_model_count_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG", logger="encodr.api.jobs")
    now = datetime(2026, 5, 5, tzinfo=timezone.utc)

    with import_api_module("app.schemas.jobs") as jobs:
        operation = jobs.BulkQueueOperation(
            id="bulk-1",
            selection_hash="hash",
            scope="folder",
            status="completed",
            stage="completed",
            batch_size=25,
            total_expected=2,
            discovered_count=2,
            queued_count=None,
            skipped_count=None,
            blocked_count=None,
            failed_count=None,
            current_batch=1,
            total_batches=1,
            payload={},
            result_summary={"queued": 2, "skipped_count": "", "blocked": "bad"},
            created_at=now,
            updated_at=now,
        )

        response = jobs.BulkQueueOperationResponse.from_model(operation)

    assert response.queued_count == 2
    assert response.skipped_count == 0
    assert response.blocked_count == 0
    assert response.failed_count == 0

    record = next(record for record in caplog.records if getattr(record, "event", None) == "bulk_queue_operation_summary_normalised")
    assert getattr(record, "operation_id", None) == "bulk-1"
    assert getattr(record, "missing_fields", None) == ["queued_count", "skipped_count", "blocked_count", "failed_count"]
