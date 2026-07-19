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

class WorkerInventoryService(WorkerBaseService):
    def list_worker_inventory(
        self,
        session: Session,
        *,
        include_disabled: bool = True,
    ) -> list[dict[str, object]]:
        repository = WorkerRepository(session)
        local_worker = resolve_local_worker_configuration(
            session,
            config_bundle=self.config_bundle,
            worker_name=self.local_worker_loop.worker_name,
        ).worker
        items: list[dict[str, object]] = []
        if local_worker is not None and (include_disabled or local_worker.enabled):
            items.append(self._local_worker_inventory(worker=local_worker))
        remote_workers = repository.list_workers(
            worker_type=WorkerType.REMOTE,
            enabled=None if include_disabled else True,
        )
        items.extend(self._remote_worker_summary(worker) for worker in remote_workers)
        items.sort(
            key=lambda item: (
                0 if item["worker_type"] == WorkerType.LOCAL.value else 1,
                item["display_name"].lower(),
            )
        )
        return items

    def get_worker_inventory_item(self, session: Session, *, worker_id: str) -> dict[str, object]:
        repository = WorkerRepository(session)
        local_worker = resolve_local_worker_configuration(
            session,
            config_bundle=self.config_bundle,
            worker_name=self.local_worker_loop.worker_name,
        ).worker
        if local_worker is not None and worker_id in {local_worker.id, local_worker.worker_key}:
            return self._local_worker_inventory(worker=local_worker, detail=True)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        return self._remote_worker_summary(worker, detail=True)

    def _local_worker_inventory(self, *, worker: Worker, detail: bool = False) -> dict[str, object]:
        status = self.status_summary(local_worker_override=worker)
        has_fresh_runtime_payload = self._local_worker_runtime_payload_is_fresh(worker)
        runtime_payload = worker.runtime_payload or {}
        capability_summary = (
            self._clean_capability_summary(worker.capability_payload)
            if has_fresh_runtime_payload
            else self._local_capability_summary()
        )
        current_job = self._local_current_job_snapshot(worker.id)
        current_job_id = status["current_job_id"] or current_job.get("id")
        current_backend = status["current_backend"] or current_job.get("actual_execution_backend") or current_job.get("requested_execution_backend")
        current_stage = status["current_stage"] or current_job.get("progress_stage")
        current_progress_percent = status["current_progress_percent"]
        if current_progress_percent is None:
            current_progress_percent = current_job.get("progress_percent")
        current_progress_updated_at = status["current_progress_updated_at"] or current_job.get("progress_updated_at")
        local_config = self.config_bundle.workers.local
        item: dict[str, object] = {
            "id": worker.id,
            "worker_key": worker.worker_key,
            "display_name": worker.display_name,
            "worker_type": WorkerType.LOCAL.value,
            "worker_state": status["configuration_state"],
            "source": "configured_local",
            "enabled": worker.enabled,
            "registration_status": worker.registration_status.value,
            "health_status": status["status"],
            "health_summary": status["summary"],
            "last_seen_at": worker.last_seen_at if has_fresh_runtime_payload else status["last_run_completed_at"],
            "last_heartbeat_at": worker.last_heartbeat_at if has_fresh_runtime_payload else status["last_run_completed_at"],
            "last_registration_at": worker.created_at,
            "capability_summary": capability_summary,
            "host_summary": (
                self._clean_host_summary(worker.host_metadata)
                if has_fresh_runtime_payload
                else {
                    "hostname": local_config.host,
                    "platform": None,
                    "agent_version": None,
                    "python_version": None,
                }
            ),
            "preferred_backend": worker.preferred_backend,
            "allow_cpu_fallback": worker.allow_cpu_fallback,
            "max_concurrent_jobs": worker.max_concurrent_jobs,
            "scratch_path": worker.scratch_path or str(local_config.scratch_dir),
            "path_mappings": self._validated_path_mappings(
                worker.path_mappings,
                remote_runtime_payload=None,
                validate_locally=True,
            ),
            "schedule_windows": worker.schedule_windows or [],
            "schedule_summary": schedule_windows_summary(worker.schedule_windows),
            "current_job_id": current_job_id,
            "current_backend": current_backend,
            "current_stage": current_stage,
            "current_progress_percent": current_progress_percent,
            "onboarding_platform": None,
            "pairing_expires_at": None,
            "pending_assignment_count": status["queue_health"]["pending_count"],
            "last_completed_job_id": status["last_processed_job_id"],
        }
        if detail:
            local_runtime_summary = (
                self._clean_runtime_summary(runtime_payload)
                if has_fresh_runtime_payload
                else None
            )
            item.update(
                {
                    "runtime_summary": local_runtime_summary or {
                        "queue": local_config.queue,
                        "scratch_dir": worker.scratch_path or str(local_config.scratch_dir),
                        "scratch_status": probe_directory(
                            worker.scratch_path or str(local_config.scratch_dir),
                            writable_required=True,
                        ),
                        "media_mounts": [str(path) for path in local_config.media_mounts],
                        "path_mappings": self._validated_path_mappings(
                            worker.path_mappings,
                            remote_runtime_payload=None,
                            validate_locally=True,
                        ),
                        "preferred_backend": worker.preferred_backend,
                        "allow_cpu_fallback": worker.allow_cpu_fallback,
                        "max_concurrent_jobs": worker.max_concurrent_jobs,
                        "schedule_windows": worker.schedule_windows or [],
                        "current_job_id": current_job_id,
                        "current_backend": current_backend,
                        "selected_backend": status.get("selected_backend"),
                        "backend_fallback_used": status.get("backend_fallback_used"),
                        "backend_fallback_reason": status.get("backend_fallback_reason"),
                        "qsv_usable": status.get("qsv_usable"),
                        "qsv_unavailable_reason": status.get("qsv_unavailable_reason"),
                        "vaapi_usable": status.get("vaapi_usable"),
                        "vaapi_unavailable_reason": status.get("vaapi_unavailable_reason"),
                        "backend_diagnostic": status.get("backend_diagnostic"),
                        "current_stage": current_stage,
                        "current_progress_percent": current_progress_percent,
                        "current_progress_updated_at": current_progress_updated_at,
                        "telemetry": status["telemetry"],
                        "last_completed_job_id": status["last_processed_job_id"],
                    },
                    "binary_summary": [
                        *(
                            (worker.binary_payload or {}).get("binaries", [])
                            if has_fresh_runtime_payload and isinstance(worker.binary_payload, dict)
                            else [
                                self._binary_inventory_item("ffmpeg", status["ffmpeg"]),
                                self._binary_inventory_item("ffprobe", status["ffprobe"]),
                            ]
                        )
                    ],
                    "assigned_job_ids": [str(current_job_id)] if current_job_id else [],
                    "last_processed_job_id": status["last_processed_job_id"],
                    "recent_failure_message": status["last_failure_message"],
                    "recent_jobs": self._recent_job_history(remote_worker_id=worker.id),
                }
            )
        return item

    def _local_current_job_snapshot(self, worker_id: str) -> dict[str, object]:
        if self.session_factory is None:
            return {}
        with self.session_factory() as session:
            job = session.scalar(
                select(Job)
                .where(
                    Job.assigned_worker_id == worker_id,
                    Job.status == JobStatus.RUNNING,
                )
                .order_by(desc(Job.started_at), desc(Job.updated_at))
                .limit(1)
            )
            if job is None:
                return {}
            return {
                "id": job.id,
                "requested_execution_backend": job.requested_execution_backend,
                "actual_execution_backend": job.actual_execution_backend,
                "progress_stage": job.progress_stage,
                "progress_percent": job.progress_percent,
                "progress_updated_at": job.progress_updated_at,
            }

    def _remote_worker_summary(self, worker: Worker, *, detail: bool = False) -> dict[str, object]:
        runtime_payload = worker.runtime_payload or {}
        binary_payload = worker.binary_payload or {}
        runtime_summary = self._clean_runtime_summary(runtime_payload)
        item: dict[str, object] = {
            "id": worker.id,
            "worker_key": worker.worker_key,
            "display_name": worker.display_name,
            "worker_type": worker.worker_type.value,
            "worker_state": self._remote_worker_state(worker),
            "source": "persisted_remote",
            "enabled": worker.enabled,
            "registration_status": worker.registration_status.value,
            "health_status": self._from_worker_health(worker.last_health_status),
            "health_summary": worker.last_health_summary,
            "last_seen_at": worker.last_seen_at,
            "last_heartbeat_at": worker.last_heartbeat_at,
            "last_registration_at": worker.last_registration_at,
            "capability_summary": self._clean_capability_summary(worker.capability_payload),
            "host_summary": self._clean_host_summary(worker.host_metadata),
            "preferred_backend": worker.preferred_backend,
            "allow_cpu_fallback": worker.allow_cpu_fallback,
            "max_concurrent_jobs": worker.max_concurrent_jobs,
            "scratch_path": worker.scratch_path,
            "path_mappings": runtime_summary.get("path_mappings", []),
            "schedule_windows": worker.schedule_windows or [],
            "schedule_summary": schedule_windows_summary(worker.schedule_windows),
            "current_job_id": runtime_summary.get("current_job_id"),
            "current_backend": runtime_summary.get("current_backend"),
            "current_stage": runtime_summary.get("current_stage"),
            "current_progress_percent": runtime_summary.get("current_progress_percent"),
            "onboarding_platform": worker.onboarding_platform,
            "pairing_expires_at": worker.pairing_expires_at,
            "pending_assignment_count": len(worker.assigned_jobs),
            "last_completed_job_id": runtime_summary.get("last_completed_job_id"),
        }
        if detail:
            item.update(
                {
                    "runtime_summary": runtime_summary,
                    "binary_summary": binary_payload.get("binaries", []),
                    "assigned_job_ids": [job.id for job in worker.assigned_jobs],
                    "last_processed_job_id": runtime_summary.get("last_completed_job_id"),
                    "recent_failure_message": worker.last_health_summary if worker.last_health_status == WorkerHealthStatus.FAILED else None,
                    "recent_jobs": self._recent_job_history(remote_worker_id=worker.id),
                }
            )
        return item

    def _recent_job_history(
        self,
        *,
        local_worker_name: str | None = None,
        remote_worker_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        if self.session_factory is None:
            return []
        with self.session_factory() as session:
            jobs = JobRepository(session).list_recent_for_worker(
                worker_name=local_worker_name,
                worker_id=remote_worker_id,
                limit=limit,
            )
        items: list[dict[str, object]] = []
        for job in jobs:
            duration_seconds = None
            if job.started_at is not None and job.completed_at is not None:
                started_at = job.started_at
                completed_at = job.completed_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)
                duration_seconds = max(0, int((completed_at - started_at).total_seconds()))
            items.append(
                {
                    "job_id": job.id,
                    "source_filename": job.tracked_file.source_filename if job.tracked_file is not None else None,
                    "status": job.status.value,
                    "actual_execution_backend": job.actual_execution_backend,
                    "requested_execution_backend": job.requested_execution_backend,
                    "backend_fallback_used": job.backend_fallback_used,
                    "completed_at": job.completed_at,
                    "duration_seconds": duration_seconds,
                    "failure_message": job.failure_message,
                }
            )
        return items

