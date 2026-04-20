from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from encodr_db.models import AuditEvent, AuditEventType, AuditOutcome, User
from encodr_db.repositories import AuditEventRepository


class AuditService:
    def record_event(
        self,
        session: Session,
        *,
        event_type: AuditEventType,
        outcome: AuditOutcome,
        request: Request,
        user: User | None = None,
        username: str | None = None,
        details: dict | None = None,
    ) -> AuditEvent:
        client = request.client.host if request.client is not None else None
        user_agent = request.headers.get("user-agent")
        return AuditEventRepository(session).add_event(
            event_type=event_type,
            outcome=outcome,
            user=user,
            username=username,
            source_ip=client,
            user_agent=user_agent,
            details=details,
        )
