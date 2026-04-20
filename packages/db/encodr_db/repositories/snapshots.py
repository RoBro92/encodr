from __future__ import annotations

from sqlalchemy.orm import Session

from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_db.models import FileLifecycleState, PlanSnapshot, ProbeSnapshot, TrackedFile


class ProbeSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_probe_snapshot(
        self,
        tracked_file: TrackedFile,
        media_file: MediaFile,
        *,
        schema_version: int = 1,
    ) -> ProbeSnapshot:
        snapshot = ProbeSnapshot(
            tracked_file_id=tracked_file.id,
            schema_version=schema_version,
            payload=media_file.model_dump(mode="json"),
        )
        tracked_file.lifecycle_state = FileLifecycleState.PROBED
        tracked_file.last_observed_size = media_file.container.size_bytes
        tracked_file.is_4k = media_file.is_4k
        self.session.add(snapshot)
        self.session.flush()
        return snapshot


class PlanSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_plan_snapshot(
        self,
        tracked_file: TrackedFile,
        probe_snapshot: ProbeSnapshot,
        plan: ProcessingPlan,
    ) -> PlanSnapshot:
        snapshot = PlanSnapshot(
            tracked_file_id=tracked_file.id,
            probe_snapshot_id=probe_snapshot.id,
            action=plan.action,
            confidence=plan.confidence,
            policy_version=plan.policy_context.policy_version,
            profile_name=plan.policy_context.selected_profile_name,
            is_already_compliant=plan.is_already_compliant,
            should_treat_as_protected=plan.should_treat_as_protected,
            reasons=[reason.model_dump(mode="json") for reason in plan.reasons],
            warnings=[warning.model_dump(mode="json") for warning in plan.warnings],
            selected_streams=plan.selected_streams.model_dump(mode="json"),
            payload=plan.model_dump(mode="json"),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot
