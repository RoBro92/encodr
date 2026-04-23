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

    def get_by_pairing_token_hash(self, token_hash: str) -> Worker | None:
        query = select(Worker).where(Worker.pairing_token_hash == token_hash)
        return self.session.scalar(query)

    def get_local_worker(self, worker_key: str) -> Worker | None:
        query = select(Worker).where(
            Worker.worker_key == worker_key,
            Worker.worker_type == WorkerType.LOCAL,
        )
        return self.session.scalar(query)

    def get_by_ids(self, worker_ids: list[str]) -> list[Worker]:
        if not worker_ids:
            return []
        query = select(Worker).where(Worker.id.in_(worker_ids))
        return list(self.session.scalars(query))

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
        preferred_backend: str = "cpu_only",
        allow_cpu_fallback: bool = True,
        max_concurrent_jobs: int = 1,
        path_mappings: list[dict] | None = None,
        scratch_path: str | None = None,
        host_metadata: dict | None,
        capability_payload: dict | None,
        runtime_payload: dict | None,
        binary_payload: dict | None,
        health_status: WorkerHealthStatus,
        health_summary: str | None,
        registered_at: datetime,
    ) -> Worker:
        worker = self.get_by_key(worker_key)
        created = worker is None
        if worker is None:
            worker = Worker(
                worker_key=worker_key,
                display_name=display_name,
                worker_type=WorkerType.REMOTE,
            )
            self.session.add(worker)

        worker.display_name = display_name
        worker.enabled = True if created else worker.enabled
        worker.registration_status = (
            WorkerRegistrationStatus.REGISTERED
            if worker.enabled
            else WorkerRegistrationStatus.DISABLED
        )
        worker.preferred_backend = preferred_backend
        worker.allow_cpu_fallback = allow_cpu_fallback
        worker.max_concurrent_jobs = max_concurrent_jobs
        worker.path_mappings = path_mappings
        worker.scratch_path = scratch_path
        worker.auth_token_hash = auth_token_hash
        worker.pairing_token_hash = None
        worker.pairing_requested_at = None
        worker.pairing_expires_at = None
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

    def upsert_local_worker(
        self,
        *,
        worker_key: str,
        display_name: str,
        enabled: bool,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None,
        path_mappings: list[dict] | None,
        scratch_path: str | None,
        host_metadata: dict | None,
    ) -> Worker:
        worker = self.get_local_worker(worker_key)
        if worker is None:
            worker = Worker(
                worker_key=worker_key,
                display_name=display_name,
                worker_type=WorkerType.LOCAL,
            )
            self.session.add(worker)

        worker.display_name = display_name
        worker.enabled = enabled
        worker.registration_status = (
            WorkerRegistrationStatus.REGISTERED
            if enabled
            else WorkerRegistrationStatus.DISABLED
        )
        worker.preferred_backend = preferred_backend
        worker.allow_cpu_fallback = allow_cpu_fallback
        worker.max_concurrent_jobs = max_concurrent_jobs
        worker.schedule_windows = schedule_windows
        worker.path_mappings = path_mappings
        worker.scratch_path = scratch_path
        worker.host_metadata = host_metadata
        if not enabled:
            worker.last_health_status = WorkerHealthStatus.UNKNOWN
            worker.last_health_summary = "Local worker is configured but disabled."
        self.session.flush()
        return worker

    def create_pending_remote_worker(
        self,
        *,
        worker_key: str,
        display_name: str,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None,
        path_mappings: list[dict] | None,
        scratch_path: str | None,
        pairing_token_hash: str,
        pairing_requested_at: datetime,
        pairing_expires_at: datetime,
        onboarding_platform: str,
        install_dir: str | None,
    ) -> Worker:
        worker = Worker(
            worker_key=worker_key,
            display_name=display_name,
            worker_type=WorkerType.REMOTE,
            enabled=True,
            registration_status=WorkerRegistrationStatus.UNKNOWN,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=schedule_windows,
            path_mappings=path_mappings,
            scratch_path=scratch_path,
            pairing_token_hash=pairing_token_hash,
            pairing_requested_at=pairing_requested_at,
            pairing_expires_at=pairing_expires_at,
            onboarding_platform=onboarding_platform,
            install_dir=install_dir,
            last_health_status=WorkerHealthStatus.UNKNOWN,
            last_health_summary="Worker is waiting to pair with Encodr.",
            host_metadata={"expected_platform": onboarding_platform},
        )
        self.session.add(worker)
        self.session.flush()
        return worker

    def update_preferences(
        self,
        worker: Worker,
        *,
        display_name: str | None = None,
        preferred_backend: str | None = None,
        allow_cpu_fallback: bool | None = None,
        max_concurrent_jobs: int | None = None,
        schedule_windows: list[dict] | None = None,
        path_mappings: list[dict] | None = None,
        scratch_path: str | None = None,
    ) -> Worker:
        if display_name is not None:
            worker.display_name = display_name
        if preferred_backend is not None:
            worker.preferred_backend = preferred_backend
        if allow_cpu_fallback is not None:
            worker.allow_cpu_fallback = allow_cpu_fallback
        if max_concurrent_jobs is not None:
            worker.max_concurrent_jobs = max_concurrent_jobs
        if schedule_windows is not None:
            worker.schedule_windows = schedule_windows
        if path_mappings is not None:
            worker.path_mappings = path_mappings
        if scratch_path is not None:
            worker.scratch_path = scratch_path
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
        if enabled:
            if worker.worker_type == WorkerType.LOCAL:
                worker.registration_status = WorkerRegistrationStatus.REGISTERED
            elif worker.auth_token_hash is not None:
                worker.registration_status = WorkerRegistrationStatus.REGISTERED
            else:
                worker.registration_status = WorkerRegistrationStatus.UNKNOWN
        else:
            worker.registration_status = WorkerRegistrationStatus.DISABLED
        if not enabled:
            worker.last_health_status = WorkerHealthStatus.UNKNOWN
            worker.last_health_summary = (
                "Local worker is configured but disabled."
                if worker.worker_type == WorkerType.LOCAL
                else "Worker is disabled by an administrator."
            )
        self.session.flush()
        return worker

    def delete_worker(self, worker: Worker) -> None:
        self.session.delete(worker)
        self.session.flush()
