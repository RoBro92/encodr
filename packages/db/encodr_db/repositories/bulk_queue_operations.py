from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from encodr_db.models import BulkQueueOperation

ACTIVE_BULK_QUEUE_STATUSES = {"pending", "running", "cancelling"}
TERMINAL_BULK_QUEUE_STATUSES = {"completed", "failed", "cancelled"}


class BulkQueueOperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, operation_id: str) -> BulkQueueOperation | None:
        return self.session.get(BulkQueueOperation, operation_id)

    def get_active(self) -> BulkQueueOperation | None:
        query = (
            select(BulkQueueOperation)
            .where(BulkQueueOperation.status.in_(ACTIVE_BULK_QUEUE_STATUSES))
            .order_by(desc(BulkQueueOperation.updated_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def get_active_by_selection_hash(self, selection_hash: str) -> BulkQueueOperation | None:
        query = (
            select(BulkQueueOperation)
            .where(
                BulkQueueOperation.selection_hash == selection_hash,
                BulkQueueOperation.status.in_(ACTIVE_BULK_QUEUE_STATUSES),
            )
            .order_by(desc(BulkQueueOperation.updated_at))
            .limit(1)
        )
        return self.session.scalar(query)

    def list_recent(self, *, limit: int = 10, active_only: bool = False) -> list[BulkQueueOperation]:
        query = select(BulkQueueOperation).order_by(desc(BulkQueueOperation.updated_at)).limit(limit)
        if active_only:
            query = query.where(BulkQueueOperation.status.in_(ACTIVE_BULK_QUEUE_STATUSES))
        return list(self.session.scalars(query))

    def create_operation(
        self,
        *,
        selection_hash: str,
        scope: str,
        payload: dict,
        batch_size: int,
    ) -> BulkQueueOperation:
        operation = BulkQueueOperation(
            selection_hash=selection_hash,
            scope=scope,
            payload=payload,
            batch_size=batch_size,
            status="pending",
            stage="scanning_selection",
            status_text="Scanning selection",
        )
        self.session.add(operation)
        self.session.flush()
        return operation

    def mark_running(self, operation: BulkQueueOperation, *, status_text: str) -> BulkQueueOperation:
        now = datetime.now(timezone.utc)
        operation.status = "running"
        operation.started_at = operation.started_at or now
        operation.stage = "scanning_selection"
        operation.status_text = status_text
        self.session.flush()
        return operation

    def request_cancel(self, operation: BulkQueueOperation) -> BulkQueueOperation:
        if operation.status not in ACTIVE_BULK_QUEUE_STATUSES:
            return operation
        operation.status = "cancelling"
        operation.status_text = "Cancelling bulk queue operation"
        self.session.flush()
        return operation

    def update_progress(
        self,
        operation: BulkQueueOperation,
        *,
        stage: str | None = None,
        status_text: str | None = None,
        total_expected: int | None = None,
        discovered_count: int | None = None,
        queued_count: int | None = None,
        skipped_count: int | None = None,
        blocked_count: int | None = None,
        failed_count: int | None = None,
        current_batch: int | None = None,
        total_batches: int | None = None,
        result_summary: dict | None = None,
    ) -> BulkQueueOperation:
        if stage is not None:
            operation.stage = stage
        if status_text is not None:
            operation.status_text = status_text
        if total_expected is not None:
            operation.total_expected = total_expected
        if discovered_count is not None:
            operation.discovered_count = discovered_count
        if queued_count is not None:
            operation.queued_count = queued_count
        if skipped_count is not None:
            operation.skipped_count = skipped_count
        if blocked_count is not None:
            operation.blocked_count = blocked_count
        if failed_count is not None:
            operation.failed_count = failed_count
        if current_batch is not None:
            operation.current_batch = current_batch
        if total_batches is not None:
            operation.total_batches = total_batches
        if result_summary is not None:
            operation.result_summary = result_summary
        self.session.flush()
        return operation

    def finish(
        self,
        operation: BulkQueueOperation,
        *,
        status: str,
        stage: str,
        status_text: str,
        result_summary: dict | None = None,
        error_summary: str | None = None,
    ) -> BulkQueueOperation:
        operation.status = status
        operation.stage = stage
        operation.status_text = status_text
        operation.completed_at = datetime.now(timezone.utc)
        operation.result_summary = result_summary
        operation.error_summary = error_summary
        self.session.flush()
        return operation
