from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.services.errors import ApiDependencyError, ApiNotFoundError, ApiValidationError
from encodr_core.config import ConfigBundle
from encodr_core.media.models import MediaFile
from encodr_core.probe import ProbeBinaryNotFoundError, ProbeError
from encodr_db.models import ComplianceState, FileLifecycleState, PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.repositories import PlanSnapshotRepository, ProbeSnapshotRepository, TrackedFileRepository


class FilesService:
    def __init__(
        self,
        *,
        config_bundle: ConfigBundle,
        probe_client_factory: Callable[[], object],
    ) -> None:
        self.config_bundle = config_bundle
        self.probe_client_factory = probe_client_factory

    def list_files(
        self,
        session: Session,
        *,
        lifecycle_state: FileLifecycleState | None = None,
        compliance_state: ComplianceState | None = None,
        protected_only: bool | None = None,
        path_prefix: str | None = None,
        path_search: str | None = None,
        is_4k: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TrackedFile]:
        return TrackedFileRepository(session).list_files(
            lifecycle_state=lifecycle_state,
            compliance_state=compliance_state,
            protected_only=protected_only,
            path_prefix=path_prefix,
            path_search=path_search,
            is_4k=is_4k,
            limit=limit,
            offset=offset,
        )

    def count_files(
        self,
        session: Session,
        *,
        lifecycle_state: FileLifecycleState | None = None,
        compliance_state: ComplianceState | None = None,
        protected_only: bool | None = None,
        path_prefix: str | None = None,
        path_search: str | None = None,
        is_4k: bool | None = None,
    ) -> int:
        return TrackedFileRepository(session).count_files(
            lifecycle_state=lifecycle_state,
            compliance_state=compliance_state,
            protected_only=protected_only,
            path_prefix=path_prefix,
            path_search=path_search,
            is_4k=is_4k,
        )

    def get_file(self, session: Session, *, file_id: str) -> TrackedFile:
        tracked_file = TrackedFileRepository(session).get_by_id(file_id)
        if tracked_file is None:
            raise ApiNotFoundError("Tracked file could not be found.")
        return tracked_file

    def get_latest_probe_snapshot(self, session: Session, *, file_id: str) -> ProbeSnapshot:
        tracked_file = self.get_file(session, file_id=file_id)
        snapshot = TrackedFileRepository(session).get_latest_probe_snapshot(tracked_file.id)
        if snapshot is None:
            raise ApiNotFoundError("No probe snapshot exists for this tracked file.")
        return snapshot

    def get_latest_plan_snapshot(self, session: Session, *, file_id: str) -> PlanSnapshot:
        tracked_file = self.get_file(session, file_id=file_id)
        snapshot = TrackedFileRepository(session).get_latest_plan_snapshot(tracked_file.id)
        if snapshot is None:
            raise ApiNotFoundError("No plan snapshot exists for this tracked file.")
        return snapshot

    def probe_file(
        self,
        session: Session,
        *,
        source_path: str,
    ) -> tuple[TrackedFile, ProbeSnapshot]:
        resolved_path = self._resolve_source_file(source_path)
        media_file = self._probe_media_file(resolved_path)
        stat_result = resolved_path.stat()
        tracked_files = TrackedFileRepository(session)
        tracked_file = tracked_files.upsert_by_path(
            resolved_path,
            media_file=media_file,
            last_observed_modified_time=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
        )
        probe_snapshot = ProbeSnapshotRepository(session).add_probe_snapshot(tracked_file, media_file)
        return tracked_file, probe_snapshot

    def resolve_source_file(self, source_path: str) -> Path:
        return self._resolve_source_file(source_path)

    def probe_source_file(self, source_path: str) -> MediaFile:
        resolved_path = self._resolve_source_file(source_path)
        return self._probe_media_file(resolved_path)

    def _resolve_source_file(self, source_path: str) -> Path:
        raw_path = Path(source_path).expanduser()
        if not raw_path.exists():
            raise ApiNotFoundError("The source path does not exist.")
        if not raw_path.is_file():
            raise ApiValidationError("The source path must point to a file.")
        return raw_path.resolve()

    def _probe_media_file(self, source_path: Path) -> MediaFile:
        try:
            probe_client = self.probe_client_factory()
            return probe_client.probe_file(source_path)
        except ProbeBinaryNotFoundError as error:
            raise ApiDependencyError(error.message) from error
        except ProbeError as error:
            raise ApiValidationError(error.message) from error
