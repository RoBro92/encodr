from __future__ import annotations

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, joinedload

from encodr_db.models import ManualReviewDecision, ManualReviewDecisionType, User


class ManualReviewDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_decision(
        self,
        *,
        tracked_file_id: str,
        created_by_user: User,
        decision_type: ManualReviewDecisionType,
        plan_snapshot_id: str | None = None,
        job_id: str | None = None,
        note: str | None = None,
        details: dict | None = None,
    ) -> ManualReviewDecision:
        decision = ManualReviewDecision(
            tracked_file_id=tracked_file_id,
            plan_snapshot_id=plan_snapshot_id,
            job_id=job_id,
            decision_type=decision_type,
            note=note,
            created_by_user_id=created_by_user.id,
            details=details,
        )
        self.session.add(decision)
        self.session.flush()
        return decision

    def get_by_id(self, decision_id: str) -> ManualReviewDecision | None:
        query = (
            select(ManualReviewDecision)
            .where(ManualReviewDecision.id == decision_id)
            .options(joinedload(ManualReviewDecision.created_by_user))
        )
        return self.session.scalar(query)

    def get_latest_for_tracked_file(self, tracked_file_id: str) -> ManualReviewDecision | None:
        query: Select[tuple[ManualReviewDecision]] = (
            select(ManualReviewDecision)
            .where(ManualReviewDecision.tracked_file_id == tracked_file_id)
            .options(joinedload(ManualReviewDecision.created_by_user))
            .order_by(desc(ManualReviewDecision.created_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def list_for_tracked_file(self, tracked_file_id: str) -> list[ManualReviewDecision]:
        query: Select[tuple[ManualReviewDecision]] = (
            select(ManualReviewDecision)
            .where(ManualReviewDecision.tracked_file_id == tracked_file_id)
            .options(joinedload(ManualReviewDecision.created_by_user))
            .order_by(desc(ManualReviewDecision.created_at))
        )
        return list(self.session.scalars(query))

    def list_tracked_file_ids_with_decisions(self) -> list[str]:
        rows = self.session.execute(
            select(ManualReviewDecision.tracked_file_id).distinct()
        ).all()
        return [tracked_file_id for (tracked_file_id,) in rows]
