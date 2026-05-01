from __future__ import annotations

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
