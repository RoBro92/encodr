from __future__ import annotations

import copy
import ipaddress
import logging
import os
import shlex
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.worker import HealthStatus
from app.services.audit import AuditService
from app.services.errors import ApiAuthenticationError, ApiConflictError, ApiNotFoundError, ApiValidationError
from app.services.path_safety import (
    configured_path_roots,
    path_roots_with_extra_scratch_roots,
    remap_worker_path_to_server_path,
    remap_worker_payload_paths,
    validate_backup_path,
    validate_final_output_path,
    validate_output_path,
    validate_replacement_payload_paths,
)
from app.services.setup import SetupStateService
from encodr_core.config import ConfigBundle
from encodr_core.execution import ExecutionProgressUpdate, ExecutionResult, normalise_backend_preference
from encodr_core.planning import ProcessingPlan
from encodr_db.models import (
    AuditEventType,
    AuditOutcome,
    JobKind,
    JobStatus,
    Job,
    User,
    Worker,
    WorkerHealthStatus,
    WorkerRegistrationStatus,
    WorkerType,
)
from encodr_db.repositories import JobRepository, TrackedFileRepository, WorkerRepository
from encodr_db.runtime import (
    LOCAL_WORKER_CAPABILITY_SOURCE,
    LocalWorkerLoop,
    WorkerRunSummary,
    job_allows_worker,
    resolve_local_worker_configuration,
    worker_is_dispatchable,
)
from encodr_shared import (
    collect_runtime_telemetry,
    clean_runtime_summary_payload,
    coerce_backend_preference,
    ensure_mapping_marker,
    hardware_hints_from_backend_probes,
    merge_runtime_summary_preferences,
    normalise_path_mappings,
    read_version,
    recommend_worker_concurrency,
    remap_server_path,
    validate_worker_path_mapping,
)
from encodr_shared.scheduling import normalise_schedule_windows, schedule_windows_summary
from encodr_shared.worker_runtime import (
    backend_probe_matches_preference,
    discover_runtime_devices,
    probe_binary,
    probe_directory,
    probe_execution_backends,
    resolve_backend_runtime_status,
    serialise_backend_probe,
)

logger = logging.getLogger("encodr.api.worker_service")

from .base import WorkerBaseService, _worker_log_extra, age_seconds

class WorkerSetupService(WorkerBaseService):
    def setup_local_worker(
        self,
        session: Session,
        *,
        display_name: str | None,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None = None,
        scratch_path: str | None = None,
        path_mappings: list[dict] | None = None,
    ) -> dict[str, object]:
        self._validate_local_backend_preferences(
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            session=session,
        )
        try:
            cleaned_schedule = normalise_schedule_windows(schedule_windows)
        except ValueError as error:
            raise ApiConflictError(str(error)) from error
        repository = WorkerRepository(session)
        worker = repository.upsert_local_worker(
            worker_key=self.config_bundle.workers.local.id,
            display_name=display_name or self.local_worker_loop.worker_name,
            enabled=True,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=cleaned_schedule,
            path_mappings=normalise_path_mappings(path_mappings),
            scratch_path=scratch_path or str(self.config_bundle.workers.local.scratch_dir),
            host_metadata={"hostname": self.config_bundle.workers.local.host},
        )
        return self._local_worker_inventory(worker=worker, detail=True)

    def update_worker_preferences(
        self,
        session: Session,
        *,
        worker_id: str,
        display_name: str | None,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None = None,
        scratch_path: str | None = None,
        path_mappings: list[dict] | None = None,
    ) -> dict[str, object]:
        repository = WorkerRepository(session)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        if worker.worker_type == WorkerType.LOCAL:
            self._validate_local_backend_preferences(
                preferred_backend=preferred_backend,
                allow_cpu_fallback=allow_cpu_fallback,
                local_worker=worker,
            )
        try:
            cleaned_schedule = normalise_schedule_windows(schedule_windows)
        except ValueError as error:
            raise ApiConflictError(str(error)) from error
        repository.update_preferences(
            worker,
            display_name=display_name,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=cleaned_schedule,
            path_mappings=normalise_path_mappings(path_mappings),
            scratch_path=scratch_path,
        )
        if worker.worker_type == WorkerType.LOCAL:
            return self._local_worker_inventory(worker=worker, detail=True)
        return self._remote_worker_summary(worker, detail=True)

    def set_worker_enabled(
        self,
        session: Session,
        *,
        worker_id: str,
        enabled: bool,
        actor: User,
        request: Request,
    ) -> dict[str, object]:
        repository = WorkerRepository(session)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        if worker.worker_type == WorkerType.LOCAL and enabled:
            self._validate_local_backend_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                local_worker=worker,
            )
        repository.set_enabled(worker, enabled=enabled)
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.WORKER_STATE_CHANGE,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=actor,
            details={
                "worker_id": worker.id,
                "worker_key": worker.worker_key,
                "enabled": enabled,
            },
        )
        if worker.worker_type == WorkerType.LOCAL:
            return self._local_worker_inventory(worker=worker, detail=True)
        return self._remote_worker_summary(worker, detail=True)

    def delete_worker(
        self,
        session: Session,
        *,
        worker_id: str,
        actor: User,
        request: Request,
    ) -> dict[str, object]:
        repository = WorkerRepository(session)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        if worker.worker_type == WorkerType.LOCAL:
            raise ApiConflictError("Local worker records cannot be deleted. Disable the local worker instead.")
        uninstall_command = self._build_remote_uninstall_command(
            platform=worker.onboarding_platform or "linux",
            worker=worker,
        )
        notes = self._remote_uninstall_notes(platform=worker.onboarding_platform or "linux")
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.WORKER_STATE_CHANGE,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            user=actor,
            details={
                "worker_id": worker.id,
                "worker_key": worker.worker_key,
                "action": "deleted",
            },
        )
        worker_id_value = worker.id
        worker_key_value = worker.worker_key
        repository.delete_worker(worker)
        return {
            "worker_id": worker_id_value,
            "worker_key": worker_key_value,
            "status": "removed",
            "uninstall_command": uninstall_command,
            "notes": notes,
        }

    def _validate_local_backend_preferences(
        self,
        *,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        local_worker: Worker | None = None,
        session: Session | None = None,
    ) -> None:
        execution_preferences = {
            "preferred_backend": preferred_backend,
            "allow_cpu_fallback": allow_cpu_fallback,
        }
        if local_worker is None and session is not None:
            local_worker = resolve_local_worker_configuration(
                session,
                config_bundle=self.config_bundle,
                worker_name=self.local_worker_loop.worker_name,
            ).worker
        runtime_probes = (
            self._local_runtime_probes_from_worker_payload(
                local_worker,
                execution_preferences=execution_preferences,
            )
            if self._local_worker_runtime_payload_is_fresh(local_worker)
            else None
        )
        if runtime_probes is None:
            runtime_probes = self._local_runtime_probes(execution_preferences=execution_preferences)
        backend_status = runtime_probes.get("backend_runtime_status") or {}
        if normalise_backend_preference(preferred_backend) == "cpu":
            return
        preferred_probe = runtime_probes.get("preferred_backend_probe")
        if preferred_probe is None:
            raise ApiConflictError("The selected local backend is not recognised.")
        if not backend_status.get("transcode_backend_usable"):
            raise ApiConflictError(
                "The selected local backend is unavailable in this runtime and CPU fallback is disabled."
            )

