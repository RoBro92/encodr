from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from encodr_db.models import Worker, WorkerHealthStatus, WorkerRegistrationStatus, WorkerType


class WorkerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, worker_id: str) -> Worker | None:
        return self.session.get(Worker, worker_id)

    def get_by_key(self, worker_key: str) -> Worker | None:
        query = select(Worker).where(Worker.worker_key == worker_key)
        return self.session.scalar(query)

    def get_by_token_hash(self, token_hash: str) -> Worker | None:
        query = select(Worker).where(Worker.auth_token_hash == token_hash)
        return self.session.scalar(query)

    def list_workers(
        self,
        *,
        worker_type: WorkerType | None = None,
        enabled: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Worker]:
        query: Select[tuple[Worker]] = select(Worker).order_by(desc(Worker.updated_at))
        if worker_type is not None:
            query = query.where(Worker.worker_type == worker_type)
        if enabled is not None:
            query = query.where(Worker.enabled.is_(enabled))
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def register_remote_worker(
        self,
        *,
        worker_key: str,
        display_name: str,
        auth_token_hash: str,
        host_metadata: dict | None,
        capability_payload: dict | None,
        runtime_payload: dict | None,
        binary_payload: dict | None,
        health_status: WorkerHealthStatus,
        health_summary: str | None,
        registered_at: datetime,
    ) -> Worker:
        worker = self.get_by_key(worker_key)
        if worker is None:
            worker = Worker(
                worker_key=worker_key,
                display_name=display_name,
                worker_type=WorkerType.REMOTE,
            )
            self.session.add(worker)

        worker.display_name = display_name
        worker.enabled = True
        worker.registration_status = WorkerRegistrationStatus.REGISTERED
        worker.auth_token_hash = auth_token_hash
        worker.host_metadata = host_metadata
        worker.capability_payload = capability_payload
        worker.runtime_payload = runtime_payload
        worker.binary_payload = binary_payload
        worker.last_registration_at = registered_at
        worker.last_seen_at = registered_at
        worker.last_heartbeat_at = registered_at
        worker.last_health_status = health_status
        worker.last_health_summary = health_summary
        self.session.flush()
        return worker

    def record_heartbeat(
        self,
        worker: Worker,
        *,
        heartbeat_at: datetime,
        health_status: WorkerHealthStatus,
        health_summary: str | None,
        capability_payload: dict | None = None,
        runtime_payload: dict | None = None,
        binary_payload: dict | None = None,
        host_metadata: dict | None = None,
    ) -> Worker:
        worker.last_seen_at = heartbeat_at
        worker.last_heartbeat_at = heartbeat_at
        worker.last_health_status = health_status
        worker.last_health_summary = health_summary
        if capability_payload is not None:
            worker.capability_payload = capability_payload
        if runtime_payload is not None:
            worker.runtime_payload = runtime_payload
        if binary_payload is not None:
            worker.binary_payload = binary_payload
        if host_metadata is not None:
            worker.host_metadata = host_metadata
        self.session.flush()
        return worker

    def set_enabled(
        self,
        worker: Worker,
        *,
        enabled: bool,
    ) -> Worker:
        worker.enabled = enabled
        worker.registration_status = (
            WorkerRegistrationStatus.REGISTERED
            if enabled
            else WorkerRegistrationStatus.DISABLED
        )
        if not enabled:
            worker.last_health_status = WorkerHealthStatus.UNKNOWN
            worker.last_health_summary = "Worker is disabled by an administrator."
        self.session.flush()
        return worker
