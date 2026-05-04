from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.files import TrackedFileSummaryResponse
from app.schemas.jobs import JobSummaryResponse
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
from app.services.path_safety import (
    configured_path_roots,
    validate_backup_path,
    validate_final_output_path,
    validate_output_path,
)
from encodr_core.config import ConfigBundle
from encodr_db.models import (
    AuditEventType,
    AuditOutcome,
    Job,
    JobStatus,
    ManualReviewDecision,
    ManualReviewDecisionType,
    PlanSnapshot,
    ProbeSnapshot,
    ReplacementStatus as DbReplacementStatus,
    TrackedFile,
    User,
)
from encodr_db.repositories import (
    JobRepository,
    ManualReviewDecisionRepository,
    PlanSnapshotRepository,
    TrackedFileRepository,
)
from encodr_core.execution import ExecutionResult
from encodr_core.planning import PlanReason, ProcessingPlan
from encodr_core.planning.enums import PlanAction, VideoHandling
from encodr_core.replacement import ReplacementService
from encodr_core.verification import VerificationResult

logger = logging.getLogger("encodr.review")

REVIEW_STATUS_OPEN = "open"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_HELD = "held"
REVIEW_STATUS_RESOLVED = "resolved"

INFORMATIONAL_REVIEW_CODES = {
    "video_reduction_limit_applies",
    "output_larger_than_input_guard_applies",
}


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
    primary_reason: ReviewReasonResponse | None
    detail_reasons: list[ReviewReasonResponse]


class ReviewService:
    def __init__(
        self,
        *,
        config_bundle: ConfigBundle | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.config_bundle = config_bundle
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
    ) -> tuple[ReviewItemContext, ManualReviewDecision, Job | None]:
        item = self.get_item(session, item_id=item_id)
        if not item.requires_review:
            raise ApiConflictError("This item does not currently require review approval.")
        completed_job = self._complete_post_encode_approval(session, item=item)
        if completed_job is not None:
            decision = self._record_decision(
                session,
                item=item,
                actor=actor,
                request=request,
                decision_type=ManualReviewDecisionType.APPROVED,
                note=note,
                job=completed_job,
                details={"post_encode_replacement": True},
            )
            return self._build_item_context(session, item.tracked_file), decision, completed_job

        queued_job, executable_plan = self._queue_review_job(
            session,
            item=item,
            mode="approve",
        )
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.APPROVED,
            note=note,
            plan_snapshot=executable_plan,
            job=queued_job,
            details={"queued_from_review": True},
        )
        return self._build_item_context(session, item.tracked_file), decision, queued_job

    def reject_item(
        self,
        session: Session,
        *,
        item_id: str,
        note: str | None,
        actor: User,
        request: Request,
    ) -> tuple[ReviewItemContext, ManualReviewDecision, Job]:
        item = self.get_item(session, item_id=item_id)
        if not item.requires_review:
            raise ApiConflictError("This item does not currently require review rejection.")
        queued_job, strip_plan = self._queue_review_job(
            session,
            item=item,
            mode="reject",
        )
        self._delete_staged_output_if_present(item)
        decision = self._record_decision(
            session,
            item=item,
            actor=actor,
            request=request,
            decision_type=ManualReviewDecisionType.REJECTED,
            note=note,
            plan_snapshot=strip_plan,
            job=queued_job,
            details={"queued_strip_only": True},
        )
        return self._build_item_context(session, item.tracked_file), decision, queued_job

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
            primary_reason=item.primary_reason,
            detail_reasons=item.detail_reasons,
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
        primary_reason, detail_reasons = self._split_review_reasons(reasons, warnings)

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
            primary_reason=primary_reason,
            detail_reasons=detail_reasons,
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
        if latest_decision is None:
            return REVIEW_STATUS_OPEN if requires_review else REVIEW_STATUS_RESOLVED
        if latest_decision.decision_type == ManualReviewDecisionType.APPROVED:
            if latest_decision.job_id is not None:
                return REVIEW_STATUS_RESOLVED
            return REVIEW_STATUS_APPROVED
        if latest_decision.decision_type == ManualReviewDecisionType.REJECTED:
            return REVIEW_STATUS_REJECTED
        if latest_decision.decision_type == ManualReviewDecisionType.HELD:
            return REVIEW_STATUS_HELD
        if latest_decision.decision_type == ManualReviewDecisionType.JOB_CREATED:
            return REVIEW_STATUS_RESOLVED
        if not requires_review:
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
        status_by_decision = {
            ManualReviewDecisionType.APPROVED: "approved",
            ManualReviewDecisionType.REJECTED: "rejected",
            ManualReviewDecisionType.HELD: "held",
            ManualReviewDecisionType.MARK_PROTECTED: "protected",
            ManualReviewDecisionType.CLEAR_PROTECTED: "unprotected",
        }
        status = status_by_decision.get(decision.decision_type, decision.decision_type.value)
        logger.info(
            "review decision recorded",
            extra={
                "event": f"review_item_{status}",
                "tracked_file_id": item.tracked_file.id,
                "file_id": item.tracked_file.id,
                "job_id": decision.job_id,
                "status": status,
                "decision_id": decision.id,
                "decision_type": decision.decision_type.value,
                "plan_snapshot_id": decision.plan_snapshot_id,
            },
        )
        return decision

    def _queue_review_job(
        self,
        session: Session,
        *,
        item: ReviewItemContext,
        mode: str,
    ) -> tuple[Job, PlanSnapshot]:
        if item.latest_plan is None or item.latest_probe is None:
            raise ApiConflictError("No complete plan exists for this review item.")
        repository = JobRepository(session)
        TrackedFileRepository(session).lock_for_update(item.tracked_file.id)
        session.refresh(item.tracked_file)
        if repository.has_active_job_for_tracked_file(item.tracked_file.id):
            raise ApiConflictError("An active job already exists for this tracked file.")

        source_plan = ProcessingPlan.model_validate(item.latest_plan.payload)
        executable_plan = (
            self._approved_execution_plan(source_plan)
            if mode == "approve"
            else self._strip_only_plan(source_plan)
        )
        try:
            with session.begin_nested():
                plan_snapshot = PlanSnapshotRepository(session).add_plan_snapshot(
                    item.tracked_file,
                    item.latest_probe,
                    executable_plan,
                )
                job = repository.create_job_from_plan(
                    item.tracked_file,
                    plan_snapshot,
                    backup_policy=item.latest_job.backup_policy if item.latest_job is not None else "keep",
                )
        except IntegrityError as error:
            if repository.has_active_job_for_tracked_file(item.tracked_file.id):
                raise ApiConflictError("An active job already exists for this tracked file.") from error
            raise
        return job, plan_snapshot

    def _complete_post_encode_approval(
        self,
        session: Session,
        *,
        item: ReviewItemContext,
    ) -> Job | None:
        job = item.latest_job
        if job is None or item.latest_plan is None or job.status != JobStatus.MANUAL_REVIEW:
            return None
        if job.output_path is None:
            return None
        staged_output = self._staged_output_path(job.output_path)
        if not staged_output.exists():
            return None
        if job.replacement_status == DbReplacementStatus.SUCCEEDED:
            return job

        plan = ProcessingPlan.model_validate(item.latest_plan.payload)
        source_path = self._media_path(item.tracked_file.source_path, label="source_path")
        if source_path is None:
            raise ApiConflictError("The reviewed file does not have a valid source path.")
        replacement = ReplacementService().place_verified_output(
            source_path=source_path,
            staged_output_path=staged_output,
            plan=plan,
        )
        if replacement.status != "succeeded":
            raise ApiConflictError(replacement.failure_message or "Verified output placement failed.")
        final_output_path = self._media_path(
            replacement.final_output_path,
            label="replacement.final_output_path",
        )
        if final_output_path is None:
            raise ApiConflictError("Verified output placement did not report a final output path.")
        original_backup_path = self._backup_path(
            replacement.original_backup_path,
            label="replacement.original_backup_path",
        )
        verification = (
            VerificationResult.model_validate(job.verification_payload)
            if job.verification_payload
            else None
        )
        completed_at = datetime.now(timezone.utc)
        result = ExecutionResult(
            mode="transcode" if plan.video.transcode_required else "remux",
            status="completed",
            command=job.execution_command or [],
            output_path=staged_output,
            final_output_path=final_output_path,
            original_backup_path=original_backup_path,
            input_size_bytes=job.input_size_bytes,
            output_size_bytes=job.output_size_bytes,
            space_saved_bytes=job.space_saved_bytes,
            video_input_size_bytes=job.video_input_size_bytes,
            video_output_size_bytes=job.video_output_size_bytes,
            video_space_saved_bytes=job.video_space_saved_bytes,
            non_video_space_saved_bytes=job.non_video_space_saved_bytes,
            compression_reduction_percent=job.compression_reduction_percent,
            stdout=job.execution_stdout,
            stderr=job.execution_stderr,
            requested_backend=job.requested_execution_backend,
            actual_backend=job.actual_execution_backend,
            actual_accelerator=job.actual_execution_accelerator,
            backend_fallback_used=job.backend_fallback_used,
            backend_selection_reason=job.backend_selection_reason,
            verification=verification,
            replacement=replacement.model_copy(
                update={
                    "final_output_path": final_output_path,
                    "original_backup_path": original_backup_path,
                }
            ),
            started_at=job.started_at or completed_at,
            completed_at=completed_at,
        )
        JobRepository(session).mark_result(job, result)
        TrackedFileRepository(session).update_file_state_from_execution_result(
            job.tracked_file,
            plan,
            result,
        )
        return job

    @staticmethod
    def _approved_execution_plan(plan: ProcessingPlan) -> ProcessingPlan:
        updated = plan.model_copy(deep=True)
        updated.action = PlanAction.TRANSCODE if updated.video.transcode_required else PlanAction.REMUX
        updated.summary.action = updated.action
        updated.should_treat_as_protected = False
        updated.summary.should_treat_as_protected = False
        updated.is_already_compliant = False
        updated.summary.is_already_compliant = False
        updated.reasons = [
            *[reason for reason in updated.reasons if reason.code not in INFORMATIONAL_REVIEW_CODES],
            PlanReason(
                code="operator_approved_manual_review",
                message="Operator approved processing after manual review.",
            ),
        ]
        return updated

    @staticmethod
    def _strip_only_plan(plan: ProcessingPlan) -> ProcessingPlan:
        updated = plan.model_copy(deep=True)
        updated.action = PlanAction.REMUX
        updated.summary.action = PlanAction.REMUX
        updated.should_treat_as_protected = False
        updated.summary.should_treat_as_protected = False
        updated.is_already_compliant = False
        updated.summary.is_already_compliant = False
        updated.video.transcode_required = False
        updated.video.preserve_original = True
        updated.video.handling = VideoHandling.PRESERVE
        updated.video.max_allowed_video_reduction_percent = None
        updated.reasons = [
            PlanReason(
                code="operator_rejected_video_transcode",
                message="Operator rejected video transcoding; video will be copied while stream cleanup is applied.",
            )
        ]
        updated.warnings = [
            warning for warning in updated.warnings if warning.code not in INFORMATIONAL_REVIEW_CODES
        ]
        return updated

    def _delete_staged_output_if_present(self, item: ReviewItemContext) -> None:
        job = item.latest_job
        if job is None or job.output_path is None:
            return
        if job.status != JobStatus.MANUAL_REVIEW or job.replacement_status == DbReplacementStatus.SUCCEEDED:
            return
        try:
            self._staged_output_path(job.output_path).unlink()
        except ApiValidationError:
            return
        except FileNotFoundError:
            return
        except OSError:
            return

    def _staged_output_path(self, path: Path | str | None) -> Path:
        if self.config_bundle is None:
            if path is None:
                raise ApiValidationError("output_path is required.")
            return Path(path)
        safe_path = validate_output_path(
            path,
            configured_path_roots(self.config_bundle),
            label="output_path",
        )
        if safe_path is None:
            raise ApiValidationError("output_path is required.")
        return safe_path

    def _media_path(self, path: Path | str | None, *, label: str) -> Path | None:
        if path is None:
            return None
        if self.config_bundle is None:
            return Path(path)
        return validate_final_output_path(
            path,
            configured_path_roots(self.config_bundle),
            label=label,
        )

    def _backup_path(self, path: Path | str | None, *, label: str) -> Path | None:
        if path is None:
            return None
        if self.config_bundle is None:
            return Path(path)
        return validate_backup_path(
            path,
            configured_path_roots(self.config_bundle),
            label=label,
        )

    @staticmethod
    def _split_review_reasons(
        reasons: list[ReviewReasonResponse],
        warnings: list[ReviewReasonResponse],
    ) -> tuple[ReviewReasonResponse | None, list[ReviewReasonResponse]]:
        all_items = [*reasons, *warnings]
        primary = next((item for item in all_items if item.kind == "job"), None)
        if primary is None:
            primary = next(
                (item for item in reasons if item.code not in INFORMATIONAL_REVIEW_CODES),
                None,
            )
        if primary is None:
            primary = next(
                (item for item in warnings if item.code not in INFORMATIONAL_REVIEW_CODES),
                None,
            )
        if primary is None and all_items:
            primary = all_items[0]

        detail_reasons = [
            ReviewReasonResponse(
                code=item.code,
                message=item.message,
                kind="detail" if item.code in INFORMATIONAL_REVIEW_CODES else item.kind,
            )
            for item in all_items
            if primary is None or item.code != primary.code or item.message != primary.message
        ]
        return primary, detail_reasons

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
