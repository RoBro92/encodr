from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from app.schemas.files import TrackedFileSummaryResponse
from app.schemas.jobs import JobDetailResponse, JobSummaryResponse
from app.schemas.plans import PlanSnapshotSummaryResponse
from app.schemas.review import (
    ProtectedStateSummaryResponse,
    ReviewDecisionSummaryResponse,
    ReviewItemDetailResponse,
    ReviewItemSummaryResponse,
    ReviewReasonResponse,
)
from app.services.audit import AuditService
from app.services.errors import ApiConflictError, ApiNotFoundError, ApiValidationError
from app.services.jobs import JobsService
from app.services.plans import PlansService
from encodr_db.models import (
    AuditEventType,
    AuditOutcome,
    ComplianceState,
    FileLifecycleState,
    Job,
    JobStatus,
    ManualReviewDecision,
    ManualReviewDecisionType,
    PlanSnapshot,
    ProbeSnapshot,
    TrackedFile,
    User,
)
from encodr_db.repositories import (
    JobRepository,
    ManualReviewDecisionRepository,
    TrackedFileRepository,
)

REVIEW_STATUS_OPEN = "open"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_HELD = "held"
REVIEW_STATUS_RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class ReviewItemContext:
    tracked_file: TrackedFile
    latest_probe: ProbeSnapshot | None
    latest_plan: PlanSnapshot | None
    latest_job: Job | None
    latest_decision: ManualReviewDecision | None
    review_status: str
    requires_review: bool
    confidence: str | None
    protected_state: ProtectedStateSummaryResponse
    reasons: list[ReviewReasonResponse]
    warnings: list[ReviewReasonResponse]


class ReviewService:
    def __init__(
        self,
        *,
        plans_service: PlansService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.plans_service = plans_service
        self.audit_service = audit_service or AuditService()

    def list_items(
        self,
        session: Session,
        *,
        status: str | None = None,
        protected_only: bool | None = None,
        is_4k: bool | None = None,
        recent_failures_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReviewItemContext]:
        tracked_files = TrackedFileRepository(session)
        decision_repository = ManualReviewDecisionRepository(session)

        candidates_by_id = {
            item.id: item for item in tracked_files.list_review_candidates()
        }
        for tracked_file_id in decision_repository.list_tracked_file_ids_with_decisions():
            tracked_file = tracked_files.get_by_id(tracked_file_id)
            if tracked_file is not None:
                candidates_by_id.setdefault(tracked_file.id, tracked_file)

        items = [
            self._build_item_context(session, tracked_file)
            for tracked_file in candidates_by_id.values()
        ]
        filtered = [
            item
            for item in items
            if self._matches_filters(
                item,
                status=status,
                protected_only=protected_only,
                is_4k=is_4k,
                recent_failures_only=recent_failures_only,
            )
        ]
        filtered.sort(key=lambda item: item.tracked_file.updated_at, reverse=True)
        if offset:
            filtered = filtered[offset:]
        if limit is not None:
            filtered = filtered[:limit]
        return filtered

    def get_item(self, session: Session, *, item_id: str) -> ReviewItemContext:
        tracked_file = TrackedFileRepository(session).get_by_id(item_id)
        if tracked_file is None:
            raise ApiNotFoundError("Review item could not be found.")

        item = self._build_item_context(session, tracked_file)
        history = ManualReviewDecisionRepository(session).list_for_tracked_file(tracked_file.id)
        if not item.requires_review and not history:
            raise ApiNotFoundError("Review item could not be found.")
        return item

    def approve_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        item = self.get_item(session, item_id=item_id)
        if not item.requires_review:
            raise ApiConflictError("This item does not currently require review approval.")
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.APPROVED,
            note=note,
        )
        return self._build_item_context(session, item.tracked_file), decision

    def reject_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        item = self.get_item(session, item_id=item_id)
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.REJECTED,
            note=note,
        )
        return self._build_item_context(session, item.tracked_file), decision

    def hold_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        item = self.get_item(session, item_id=item_id)
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.HELD,
            note=note,
        )
        return self._build_item_context(session, item.tracked_file), decision

    def mark_protected(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        tracked_files = TrackedFileRepository(session)
        item = self.get_item(session, item_id=item_id)
        now = datetime.now(timezone.utc)
        tracked_files.set_operator_protected(
            item.tracked_file,
            value=True,
            note=note,
            user_id=actor.id,
            updated_at=now,
        )
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.MARK_PROTECTED,
            note=note,
            details={"operator_protected": True},
        )
        return self._build_item_context(session, item.tracked_file), decision

    def clear_protected(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        tracked_files = TrackedFileRepository(session)
        item = self.get_item(session, item_id=item_id)
        if not item.tracked_file.operator_protected:
            raise ApiConflictError("Only operator-applied protection can be cleared.")
        now = datetime.now(timezone.utc)
        tracked_files.set_operator_protected(
            item.tracked_file,
            value=False,
            note=note,
            user_id=actor.id,
            updated_at=now,
        )
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.CLEAR_PROTECTED,
            note=note,
            details={"operator_protected": False},
        )
        return self._build_item_context(session, item.tracked_file), decision

    def replan_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        item = self.get_item(session, item_id=item_id)
        tracked_file, _probe_snapshot, plan_snapshot = self.plans_service.plan_file(
            session,
            source_path=item.tracked_file.source_path,
        )
        refreshed = self._build_item_context(session, tracked_file)
        decision = self._record_decision(
            session,
            item=refreshed,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.REPLAN_REQUESTED,
            note=note,
            plan_snapshot=plan_snapshot,
        )
        return self._build_item_context(session, tracked_file), decision

    def create_job(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision, Job]:
        item = self.get_item(session, item_id=item_id)
        if item.review_status != REVIEW_STATUS_APPROVED:
            raise ApiConflictError("Manual-review items must be approved before a job can be created.")
        if item.latest_plan is None:
            raise ApiConflictError("No plan snapshot exists for this review item.")

        job = JobsService().create_job(
            session,
            tracked_file_id=item.tracked_file.id,
            allow_review_approved=True,
        )
        refreshed = self._build_item_context(session, item.tracked_file)
        decision = self._record_decision(
            session,
            item=refreshed,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.JOB_CREATED,
            note=note,
            plan_snapshot=item.latest_plan,
            job=job,
        )
        return self._build_item_context(session, item.tracked_file), decision, job

    def exclude_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision]:
        item = self.get_item(session, item_id=item_id)
        now = datetime.now(timezone.utc)
        if item.latest_job is not None and item.latest_job.status in {
            JobStatus.FAILED,
            JobStatus.MANUAL_REVIEW,
            JobStatus.SKIPPED,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLED,
        }:
            JobRepository(session).mark_cleared(
                item.latest_job,
                cleared_at=now,
                reason="Excluded from future processing by operator.",
            )

        item.tracked_file.lifecycle_state = FileLifecycleState.COMPLETED
        item.tracked_file.compliance_state = ComplianceState.COMPLIANT
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.EXCLUDED,
            note=note,
            details={
                "excluded": True,
                "reason": "operator_excluded_from_future_processing",
                "latest_job_id": item.latest_job.id if item.latest_job is not None else None,
            },
        )
        session.flush()
        return self._build_item_context(session, item.tracked_file), decision

    def to_summary_response(self, item: ReviewItemContext) -> ReviewItemSummaryResponse:
        return ReviewItemSummaryResponse(
            id=item.tracked_file.id,
            source_path=item.tracked_file.source_path,
            review_status=item.review_status,
            requires_review=item.requires_review,
            confidence=item.confidence,
            tracked_file=TrackedFileSummaryResponse.from_model(item.tracked_file),
            latest_plan=PlanSnapshotSummaryResponse.from_snapshot(item.latest_plan) if item.latest_plan else None,
            latest_job=JobSummaryResponse.from_model(item.latest_job) if item.latest_job else None,
            protected_state=item.protected_state,
            reasons=item.reasons,
            warnings=item.warnings,
            latest_probe_at=item.latest_probe.created_at if item.latest_probe else None,
            latest_plan_at=item.latest_plan.created_at if item.latest_plan else None,
            latest_job_at=item.latest_job.updated_at if item.latest_job else None,
            latest_decision=self._decision_summary(item.latest_decision),
        )

    def to_detail_response(self, item: ReviewItemContext) -> ReviewItemDetailResponse:
        return ReviewItemDetailResponse(
            **self.to_summary_response(item).model_dump(),
            latest_probe_snapshot_id=item.latest_probe.id if item.latest_probe else None,
            latest_plan_snapshot_id=item.latest_plan.id if item.latest_plan else None,
            latest_job_id=item.latest_job.id if item.latest_job else None,
        )

    def _matches_filters(
        self,
        item: ReviewItemContext,
        *,
        status: str | None,
        protected_only: bool | None,
        is_4k: bool | None,
        recent_failures_only: bool,
    ) -> bool:
        if status and item.review_status != status:
            return False
        if protected_only is True and not item.protected_state.is_protected:
            return False
        if protected_only is False and item.protected_state.is_protected:
            return False
        if is_4k is not None and item.tracked_file.is_4k != is_4k:
            return False
        if recent_failures_only and not (
            item.latest_job is not None
            and item.latest_job.status in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW}
        ):
            return False
        return True

    def _build_item_context(self, session: Session, tracked_file: TrackedFile) -> ReviewItemContext:
        tracked_files = TrackedFileRepository(session)
        latest_probe = tracked_files.get_latest_probe_snapshot(tracked_file.id)
        latest_plan = tracked_files.get_latest_plan_snapshot(tracked_file.id)
        latest_job = JobRepository(session).get_latest_for_tracked_file(tracked_file.id)
        latest_decision = ManualReviewDecisionRepository(session).get_latest_for_tracked_file(tracked_file.id)

        planner_protected = bool(latest_plan is not None and latest_plan.should_treat_as_protected)
        operator_protected = tracked_file.operator_protected
        is_protected = planner_protected or operator_protected or tracked_file.is_protected

        reasons = [
            ReviewReasonResponse(code=reason.get("code", "unknown"), message=reason.get("message", ""), kind="reason")
            for reason in (latest_plan.reasons if latest_plan is not None else [])
        ]
        warnings = [
            ReviewReasonResponse(code=warning.get("code", "unknown"), message=warning.get("message", ""), kind="warning")
            for warning in (latest_plan.warnings if latest_plan is not None else [])
        ]
        if latest_job is not None and latest_job.status in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW}:
            warnings.append(
                ReviewReasonResponse(
                    code=latest_job.failure_category or "job_requires_review",
                    message=latest_job.failure_message or "The latest job requires manual review or failed.",
                    kind="job",
                )
            )

        protected_reason_codes = []
        if planner_protected and latest_plan is not None:
            protected_reason_codes = [reason.get("code", "") for reason in latest_plan.reasons if reason.get("code")]

        if planner_protected and operator_protected:
            protected_source = "planner_and_operator"
        elif operator_protected:
            protected_source = "operator"
        elif planner_protected or tracked_file.is_protected:
            protected_source = "planner"
        else:
            protected_source = "none"

        protected_state = ProtectedStateSummaryResponse(
            is_protected=is_protected,
            planner_protected=planner_protected,
            operator_protected=operator_protected,
            source=protected_source,
            reason_codes=protected_reason_codes,
            note=tracked_file.operator_protected_note,
            updated_at=tracked_file.operator_protected_updated_at,
            updated_by_username=(
                tracked_file.operator_protected_by_user.username
                if getattr(tracked_file, "operator_protected_by_user", None) is not None
                else None
            ),
        )

        requires_review = bool(
            is_protected
            or (latest_plan is not None and latest_plan.action.value == "manual_review")
            or (latest_job is not None and latest_job.status in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW})
        )

        issue_timestamp = self._issue_timestamp(
            tracked_file=tracked_file,
            latest_plan=latest_plan,
            latest_job=latest_job,
            planner_protected=planner_protected,
        )
        effective_decision = latest_decision
        if (
            effective_decision is not None
            and issue_timestamp is not None
            and self._normalise_datetime(effective_decision.created_at) < self._normalise_datetime(issue_timestamp)
        ):
            effective_decision = None

        review_status = self._review_status(
            requires_review=requires_review,
            latest_decision=effective_decision,
        )
        if effective_decision is not None and effective_decision.decision_type == ManualReviewDecisionType.EXCLUDED:
            requires_review = False
            review_status = REVIEW_STATUS_RESOLVED
        confidence = latest_plan.confidence.value if latest_plan is not None else None

        return ReviewItemContext(
            tracked_file=tracked_file,
            latest_probe=latest_probe,
            latest_plan=latest_plan,
            latest_job=latest_job,
            latest_decision=latest_decision,
            review_status=review_status,
            requires_review=requires_review,
            confidence=confidence,
            protected_state=protected_state,
            reasons=reasons,
            warnings=warnings,
        )

    def _issue_timestamp(
        self,
        *,
        tracked_file: TrackedFile,
        latest_plan: PlanSnapshot | None,
        latest_job: Job | None,
        planner_protected: bool,
    ) -> datetime | None:
        candidates: list[datetime] = []
        if latest_plan is not None and (
            latest_plan.action.value == "manual_review" or planner_protected
        ):
            candidates.append(self._normalise_datetime(latest_plan.created_at))
        if latest_job is not None and latest_job.status in {JobStatus.FAILED, JobStatus.MANUAL_REVIEW}:
            candidates.append(self._normalise_datetime(latest_job.updated_at))
        if tracked_file.operator_protected and tracked_file.operator_protected_updated_at is not None:
            candidates.append(self._normalise_datetime(tracked_file.operator_protected_updated_at))
        if not candidates:
            return None
        return max(candidates)

    def _review_status(
        self,
        *,
        requires_review: bool,
        latest_decision: ManualReviewDecision | None,
    ) -> str:
        if not requires_review:
            return REVIEW_STATUS_RESOLVED
        if latest_decision is None:
            return REVIEW_STATUS_OPEN
        if latest_decision.decision_type == ManualReviewDecisionType.APPROVED:
            return REVIEW_STATUS_APPROVED
        if latest_decision.decision_type == ManualReviewDecisionType.REJECTED:
            return REVIEW_STATUS_REJECTED
        if latest_decision.decision_type == ManualReviewDecisionType.HELD:
            return REVIEW_STATUS_HELD
        if latest_decision.decision_type == ManualReviewDecisionType.JOB_CREATED:
            return REVIEW_STATUS_RESOLVED
        if latest_decision.decision_type == ManualReviewDecisionType.EXCLUDED:
            return REVIEW_STATUS_RESOLVED
        return REVIEW_STATUS_OPEN

    def _record_decision(
        self,
        session: Session,
        *,
        item: ReviewItemContext,
        actor: User,
        request: Request,
        decision_type: ManualReviewDecisionType,
        note: str | None,
        plan_snapshot: PlanSnapshot | None = None,
        job: Job | None = None,
        details: dict | None = None,
    ) -> ManualReviewDecision:
        decision = ManualReviewDecisionRepository(session).add_decision(
            tracked_file_id=item.tracked_file.id,
            created_by_user=actor,
            decision_type=decision_type,
            plan_snapshot_id=(plan_snapshot or item.latest_plan).id if (plan_snapshot or item.latest_plan) is not None else None,
            job_id=job.id if job is not None else (item.latest_job.id if item.latest_job is not None and decision_type == ManualReviewDecisionType.JOB_CREATED else None),
            note=note,
            details=details,
        )
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.MANUAL_REVIEW_ACTION,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=actor,
            details={
                "tracked_file_id": item.tracked_file.id,
                "plan_snapshot_id": decision.plan_snapshot_id,
                "job_id": decision.job_id,
                "decision_type": decision.decision_type.value,
                "note": note,
                **(details or {}),
            },
        )
        return decision

    def _decision_summary(
        self,
        decision: ManualReviewDecision | None,
    ) -> ReviewDecisionSummaryResponse | None:
        if decision is None:
            return None
        created_by_username = (
            decision.created_by_user.username
            if getattr(decision, "created_by_user", None) is not None
            else ""
        )
        return ReviewDecisionSummaryResponse(
            id=decision.id,
            decision_type=decision.decision_type.value,
            note=decision.note,
            created_at=decision.created_at,
            created_by_user_id=decision.created_by_user_id,
            created_by_username=created_by_username,
        )

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
