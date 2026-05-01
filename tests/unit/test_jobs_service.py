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
