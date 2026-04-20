from __future__ import annotations

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from encodr_db.models import AuditEvent, AuditEventType, AuditOutcome, User


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_event(
        self,
        *,
        event_type: AuditEventType,
        outcome: AuditOutcome,
        user: User | None = None,
        username: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            outcome=outcome,
            user_id=user.id if user is not None else None,
            username=username or (user.username if user is not None else None),
            source_ip=source_ip,
            user_agent=user_agent,
            details=details,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_events(self, *, limit: int | None = None) -> list[AuditEvent]:
        query: Select[tuple[AuditEvent]] = select(AuditEvent).order_by(desc(AuditEvent.created_at))
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))
