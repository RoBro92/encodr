from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.files import TrackedFileSummaryResponse
from app.schemas.jobs import JobDetailResponse, JobSummaryResponse
from app.schemas.plans import PlanSnapshotSummaryResponse


class ReviewReasonResponse(BaseModel):
    code: str
    message: str
    kind: str


class ProtectedStateSummaryResponse(BaseModel):
    is_protected: bool
    planner_protected: bool
    operator_protected: bool
    source: str
    reason_codes: list[str]
    note: str | None = None
    updated_at: datetime | None = None
    updated_by_username: str | None = None


class ReviewDecisionSummaryResponse(BaseModel):
    id: str
    decision_type: str
    note: str | None = None
    created_at: datetime
    created_by_user_id: str
    created_by_username: str


class ReviewItemSummaryResponse(BaseModel):
    id: str
    source_path: str
    review_status: str
    requires_review: bool
    confidence: str | None = None
    tracked_file: TrackedFileSummaryResponse
    latest_plan: PlanSnapshotSummaryResponse | None = None
    latest_job: JobSummaryResponse | None = None
    protected_state: ProtectedStateSummaryResponse
    reasons: list[ReviewReasonResponse]
    warnings: list[ReviewReasonResponse]
    latest_probe_at: datetime | None = None
    latest_plan_at: datetime | None = None
    latest_job_at: datetime | None = None
    latest_decision: ReviewDecisionSummaryResponse | None = None


class ReviewItemDetailResponse(ReviewItemSummaryResponse):
    latest_probe_snapshot_id: str | None = None
    latest_plan_snapshot_id: str | None = None
    latest_job_id: str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewItemSummaryResponse]
    limit: int | None = None
    offset: int = 0


class ReviewDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReviewDecisionResponse(BaseModel):
    review_item: ReviewItemDetailResponse
    decision: ReviewDecisionSummaryResponse | None = None
    job: JobDetailResponse | None = None
