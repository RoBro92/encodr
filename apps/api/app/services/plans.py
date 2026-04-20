from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.files import FilesService
from encodr_core.config import ConfigBundle
from encodr_core.media.models import MediaFile
from encodr_core.planning import build_processing_plan
from encodr_db.models import PlanSnapshot, ProbeSnapshot, TrackedFile
from encodr_db.repositories import PlanSnapshotRepository, TrackedFileRepository


class PlansService:
    def __init__(self, *, config_bundle: ConfigBundle, files_service: FilesService) -> None:
        self.config_bundle = config_bundle
        self.files_service = files_service

    def plan_file(
        self,
        session: Session,
        *,
        source_path: str,
    ) -> tuple[TrackedFile, ProbeSnapshot, PlanSnapshot]:
        tracked_file, probe_snapshot = self.files_service.probe_file(session, source_path=source_path)
        media_file = MediaFile.model_validate(probe_snapshot.payload)
        plan = build_processing_plan(
            media_file,
            self.config_bundle,
            source_path=tracked_file.source_path,
        )
        plan_snapshot = PlanSnapshotRepository(session).add_plan_snapshot(
            tracked_file,
            probe_snapshot,
            plan,
        )
        TrackedFileRepository(session).update_file_state_from_plan_result(tracked_file, plan)
        return tracked_file, probe_snapshot, plan_snapshot
