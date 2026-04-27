from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.orm import Session, aliased

from encodr_core.execution import ExecutionResult
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_core.planning.enums import PlanAction
from encodr_db.models import ComplianceState, FileLifecycleState, Job, JobStatus, PlanSnapshot, ProbeSnapshot, TrackedFile


def _normalize_path_prefix(path_prefix: str) -> str:
    cleaned = Path(path_prefix.strip().replace("\\", "/")).as_posix()
    while len(cleaned) > 1 and cleaned.endswith("/"):
        cleaned = cleaned[:-1]
    return cleaned


def _source_path_within_prefix(path_prefix: str):
    cleaned = _normalize_path_prefix(path_prefix)
    if cleaned == "/":
        return TrackedFile.source_path.startswith("/")
    return or_(
        TrackedFile.source_path == cleaned,
        TrackedFile.source_path.startswith(f"{cleaned}/"),
    )


class TrackedFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_by_path(
        self,
        source_path: Path | str,
        *,
        media_file: MediaFile | None = None,
        last_observed_size: int | None = None,
        last_observed_modified_time: datetime | None = None,
        fingerprint_placeholder: str | None = None,
    ) -> TrackedFile:
        resolved_path = Path(source_path)
        tracked_file = self.get_by_path(resolved_path)

        if tracked_file is None:
            tracked_file = TrackedFile(
                source_path=resolved_path.as_posix(),
                source_filename=resolved_path.name,
                source_extension=resolved_path.suffix.lower().lstrip(".") or None,
                source_directory=resolved_path.parent.as_posix(),
                lifecycle_state=FileLifecycleState.DISCOVERED,
                compliance_state=ComplianceState.UNKNOWN,
            )
            self.session.add(tracked_file)

        tracked_file.source_filename = resolved_path.name
        tracked_file.source_extension = resolved_path.suffix.lower().lstrip(".") or None
        tracked_file.source_directory = resolved_path.parent.as_posix()
        tracked_file.fingerprint_placeholder = fingerprint_placeholder
        if last_observed_size is not None:
            tracked_file.last_observed_size = last_observed_size
        if last_observed_modified_time is not None:
            tracked_file.last_observed_modified_time = last_observed_modified_time
        if media_file is not None:
            tracked_file.last_observed_size = media_file.container.size_bytes
            tracked_file.is_4k = media_file.is_4k

        self.session.flush()
        return tracked_file

    def get_by_path(self, source_path: Path | str) -> TrackedFile | None:
        query = select(TrackedFile).where(TrackedFile.source_path == Path(source_path).as_posix())
        return self.session.scalar(query)

    def get_by_id(self, tracked_file_id: str) -> TrackedFile | None:
        return self.session.get(TrackedFile, tracked_file_id)

    def list_files(
        self,
        *,
        lifecycle_state: FileLifecycleState | None = None,
        compliance_state: ComplianceState | None = None,
        protected_only: bool | None = None,
        path_prefix: str | None = None,
        path_search: str | None = None,
        is_4k: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[TrackedFile]:
        query: Select[tuple[TrackedFile]] = select(TrackedFile).order_by(desc(TrackedFile.updated_at))
        if lifecycle_state is not None:
            query = query.where(TrackedFile.lifecycle_state == lifecycle_state)
        if compliance_state is not None:
            query = query.where(TrackedFile.compliance_state == compliance_state)
        if protected_only is True:
            query = query.where(TrackedFile.is_protected.is_(True))
        if protected_only is False:
            query = query.where(TrackedFile.is_protected.is_(False))
        if path_prefix:
            query = query.where(_source_path_within_prefix(path_prefix))
        if path_search:
            query = query.where(TrackedFile.source_path.ilike(f"%{path_search}%"))
        if is_4k is not None:
            query = query.where(TrackedFile.is_4k.is_(is_4k))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def count_files(
        self,
        *,
        lifecycle_state: FileLifecycleState | None = None,
        compliance_state: ComplianceState | None = None,
        protected_only: bool | None = None,
        path_prefix: str | None = None,
        path_search: str | None = None,
        is_4k: bool | None = None,
    ) -> int:
        query = select(TrackedFile.id)
        if lifecycle_state is not None:
            query = query.where(TrackedFile.lifecycle_state == lifecycle_state)
        if compliance_state is not None:
            query = query.where(TrackedFile.compliance_state == compliance_state)
        if protected_only is True:
            query = query.where(TrackedFile.is_protected.is_(True))
        if protected_only is False:
            query = query.where(TrackedFile.is_protected.is_(False))
        if path_prefix:
            query = query.where(_source_path_within_prefix(path_prefix))
        if path_search:
            query = query.where(TrackedFile.source_path.ilike(f"%{path_search}%"))
        if is_4k is not None:
            query = query.where(TrackedFile.is_4k.is_(is_4k))
        return int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)

    def list_review_candidates(self) -> list[TrackedFile]:
        failed_job = aliased(Job)
        newer_job = aliased(Job)
        manual_review_plan_exists = (
            select(PlanSnapshot.id)
            .where(
                PlanSnapshot.tracked_file_id == TrackedFile.id,
                PlanSnapshot.action == PlanAction.MANUAL_REVIEW,
            )
            .exists()
        )
        manual_review_job_exists = (
            select(Job.id)
            .where(
                Job.tracked_file_id == TrackedFile.id,
                Job.status == JobStatus.MANUAL_REVIEW,
            )
            .exists()
        )
        newer_job_exists = (
            select(newer_job.id)
            .where(
                newer_job.tracked_file_id == TrackedFile.id,
                newer_job.created_at > failed_job.created_at,
                newer_job.status.in_(
                    [
                        JobStatus.PENDING,
                        JobStatus.SCHEDULED,
                        JobStatus.RUNNING,
                        JobStatus.COMPLETED,
                        JobStatus.SKIPPED,
                        JobStatus.MANUAL_REVIEW,
                    ]
                ),
            )
            .exists()
        )
        review_job_exists = (
            select(failed_job.id)
            .where(
                failed_job.tracked_file_id == TrackedFile.id,
                failed_job.status == JobStatus.FAILED,
                ~newer_job_exists,
            )
            .exists()
        )
        query: Select[tuple[TrackedFile]] = (
            select(TrackedFile)
            .where(
                or_(
                    TrackedFile.lifecycle_state == FileLifecycleState.MANUAL_REVIEW,
                    TrackedFile.compliance_state == ComplianceState.MANUAL_REVIEW,
                    TrackedFile.is_protected.is_(True),
                    TrackedFile.operator_protected.is_(True),
                    manual_review_plan_exists,
                    manual_review_job_exists,
                    review_job_exists,
                )
            )
            .order_by(desc(TrackedFile.updated_at))
        )
        return list(self.session.scalars(query))

    def get_latest_probe_snapshot(self, tracked_file_id: str) -> ProbeSnapshot | None:
        query = (
            select(ProbeSnapshot)
            .where(ProbeSnapshot.tracked_file_id == tracked_file_id)
            .order_by(desc(ProbeSnapshot.created_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def get_latest_plan_snapshot(self, tracked_file_id: str) -> PlanSnapshot | None:
        query = (
            select(PlanSnapshot)
            .where(PlanSnapshot.tracked_file_id == tracked_file_id)
            .order_by(desc(PlanSnapshot.created_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def update_file_state_from_plan_result(
        self,
        tracked_file: TrackedFile,
        plan: ProcessingPlan,
    ) -> TrackedFile:
        tracked_file.is_protected = plan.should_treat_as_protected or tracked_file.operator_protected
        tracked_file.compliance_state = compliance_state_for_plan(plan)
        tracked_file.lifecycle_state = lifecycle_state_for_plan(plan)
        self.session.flush()
        return tracked_file

    def update_file_state_from_execution_result(
        self,
        tracked_file: TrackedFile,
        plan: ProcessingPlan,
        result: ExecutionResult,
    ) -> TrackedFile:
        tracked_file.is_protected = plan.should_treat_as_protected or tracked_file.operator_protected

        if result_marks_file_processed(result):
            tracked_file.last_processed_policy_version = plan.policy_context.policy_version
            tracked_file.last_processed_profile_name = plan.policy_context.selected_profile_name
            tracked_file.lifecycle_state = FileLifecycleState.COMPLETED
            tracked_file.compliance_state = ComplianceState.COMPLIANT
        elif result.status == "skipped":
            tracked_file.last_processed_policy_version = plan.policy_context.policy_version
            tracked_file.last_processed_profile_name = plan.policy_context.selected_profile_name
            tracked_file.lifecycle_state = FileLifecycleState.COMPLETED
            tracked_file.compliance_state = ComplianceState.COMPLIANT
        elif result.status == "manual_review":
            tracked_file.lifecycle_state = FileLifecycleState.MANUAL_REVIEW
            tracked_file.compliance_state = ComplianceState.MANUAL_REVIEW
        elif result.status == "cancelled":
            tracked_file.lifecycle_state = lifecycle_state_for_plan(plan)
            tracked_file.compliance_state = compliance_state_for_plan(plan)
        else:
            tracked_file.lifecycle_state = FileLifecycleState.FAILED
            tracked_file.compliance_state = (
                ComplianceState.MANUAL_REVIEW
                if plan.action == PlanAction.MANUAL_REVIEW
                else ComplianceState.NON_COMPLIANT
            )

        self.session.flush()
        return tracked_file

    def set_operator_protected(
        self,
        tracked_file: TrackedFile,
        *,
        value: bool,
        note: str | None,
        user_id: str | None,
        updated_at: datetime,
    ) -> TrackedFile:
        tracked_file.operator_protected = value
        tracked_file.operator_protected_note = note
        tracked_file.operator_protected_by_user_id = user_id
        tracked_file.operator_protected_updated_at = updated_at
        tracked_file.is_protected = tracked_file.is_protected or value
        if not value:
            latest_plan = self.get_latest_plan_snapshot(tracked_file.id)
            tracked_file.is_protected = bool(
                tracked_file.operator_protected
                or (latest_plan is not None and latest_plan.should_treat_as_protected)
            )
        self.session.flush()
        return tracked_file

    def already_processed_under_policy(
        self,
        source_path: Path | str,
        policy_version: int,
        *,
        profile_name: str | None = None,
    ) -> bool:
        tracked_file = self.get_by_path(source_path)
        if tracked_file is None:
            return False
        if tracked_file.last_processed_policy_version != policy_version:
            return False
        if profile_name is not None and tracked_file.last_processed_profile_name != profile_name:
            return False

        latest_plan = self.get_latest_plan_snapshot(tracked_file.id)
        if latest_plan is None:
            return False
        if latest_plan.policy_version != policy_version:
            return False
        if profile_name is not None and latest_plan.profile_name != profile_name:
            return False
        return tracked_file.compliance_state != ComplianceState.UNKNOWN


def lifecycle_state_for_plan(plan: ProcessingPlan) -> FileLifecycleState:
    if plan.action == PlanAction.MANUAL_REVIEW:
        return FileLifecycleState.MANUAL_REVIEW
    return FileLifecycleState.PLANNED


def compliance_state_for_plan(plan: ProcessingPlan) -> ComplianceState:
    if plan.action == PlanAction.MANUAL_REVIEW:
        return ComplianceState.MANUAL_REVIEW
    if plan.is_already_compliant:
        return ComplianceState.COMPLIANT
    return ComplianceState.NON_COMPLIANT


def result_marks_file_processed(result: ExecutionResult) -> bool:
    if result.status != "completed":
        return False
    if result.replacement is None or result.replacement.status != "succeeded":
        return False
    final_output_path = result.final_output_path or result.replacement.final_output_path
    if final_output_path is None:
        return False
    return Path(final_output_path).exists()
