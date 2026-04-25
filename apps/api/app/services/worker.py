from __future__ import annotations

import copy
import ipaddress
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
from app.services.errors import ApiAuthenticationError, ApiConflictError, ApiNotFoundError
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
from encodr_db.runtime import LocalWorkerLoop, WorkerRunSummary, job_allows_worker, resolve_local_worker_configuration, worker_is_dispatchable
from encodr_shared import (
    collect_runtime_telemetry,
    ensure_mapping_marker,
    mapping_for_server_path,
    normalise_path_mappings,
    read_version,
    recommend_worker_concurrency,
    remap_server_path,
    validate_worker_path_mapping,
)
from encodr_shared.scheduling import normalise_schedule_windows, schedule_windows_summary
from encodr_shared.worker_runtime import (
    discover_runtime_devices,
    probe_binary,
    probe_directory,
    probe_execution_backends,
)


class WorkerService:
    def __init__(
        self,
        *,
        config_bundle: ConfigBundle,
        local_worker_loop: LocalWorkerLoop,
        session_factory: sessionmaker | Any | None,
        worker_token_service,
        worker_auth_runtime,
        audit_service: AuditService | None = None,
    ) -> None:
        self.config_bundle = config_bundle
        self.local_worker_loop = local_worker_loop
        self.session_factory = session_factory
        self.worker_token_service = worker_token_service
        self.worker_auth_runtime = worker_auth_runtime
        self.audit_service = audit_service or AuditService()

    def run_once(self) -> WorkerRunSummary:
        return self.local_worker_loop.run_once_with_summary()

    def binary_status(self, configured_path: Path | str) -> dict[str, object]:
        probe = probe_binary(configured_path)
        return {
            "configured_path": probe.configured_path,
            "resolved_path": probe.resolved_path,
            "exists": probe.exists,
            "executable": probe.executable,
            "discoverable": probe.discoverable,
            "status": HealthStatus(probe.status),
            "message": probe.message,
        }

    def _local_runtime_probes(
        self,
        *,
        execution_preferences: dict[str, object] | None = None,
    ) -> dict[str, object]:
        ffmpeg = self.binary_status(self.config_bundle.app.media.ffmpeg_path)
        ffprobe = self.binary_status(self.config_bundle.app.media.ffprobe_path)
        scratch_path = probe_directory(
            self.config_bundle.workers.local.scratch_dir,
            writable_required=True,
        )
        media_paths = [
            probe_directory(path, writable_required=True)
            for path in self.config_bundle.workers.local.media_mounts
        ]
        execution_backend_probes = [
            self._serialise_backend_probe(item)
            for item in probe_execution_backends(self.config_bundle.app.media.ffmpeg_path)
        ]
        runtime_device_paths = discover_runtime_devices()
        execution_backends: list[str] = []
        if ffmpeg["status"] == HealthStatus.HEALTHY:
            execution_backends.extend(["remux", "transcode"])
        hardware_acceleration = [
            item["backend"]
            for item in execution_backend_probes
            if item["backend"] != "cpu" and item["usable_by_ffmpeg"]
        ]
        scratch_ready = scratch_path["status"] == "healthy"
        media_ready = all(item["status"] == "healthy" for item in media_paths) if media_paths else False
        binaries_healthy = (
            ffmpeg["status"] == HealthStatus.HEALTHY and ffprobe["status"] == HealthStatus.HEALTHY
        )
        execution_preferences = execution_preferences or SetupStateService(
            config_bundle=self.config_bundle
        ).get_execution_preferences()
        preferred_backend = str(execution_preferences["preferred_backend"])
        preferred_backend_probe = next(
            (item for item in execution_backend_probes if item["preference_key"] == preferred_backend),
            None,
        )
        transcode_backend_usable = (
            preferred_backend == "cpu_only"
            or (
                preferred_backend_probe is not None
                and (
                    preferred_backend_probe["usable_by_ffmpeg"]
                    or bool(execution_preferences["allow_cpu_fallback"])
                )
            )
        )
        eligible = bool(
            self.config_bundle.workers.local.enabled
            and binaries_healthy
            and scratch_ready
            and media_ready
        )
        if not self.config_bundle.workers.local.enabled:
            eligibility_summary = "The local worker is disabled in configuration."
        elif not binaries_healthy:
            eligibility_summary = "Required media binaries are not available."
        elif not scratch_ready:
            eligibility_summary = "The scratch path is not ready for execution."
        elif not media_ready:
            eligibility_summary = "One or more media mount paths are unavailable."
        elif not transcode_backend_usable:
            eligibility_summary = (
                "The preferred transcode backend is unavailable and CPU fallback is disabled. "
                "Remux jobs can still run, but transcodes will stay pending."
            )
        else:
            eligibility_summary = "The local worker can accept execution work."

        return {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "scratch_path": scratch_path,
            "media_paths": media_paths,
            "execution_backends": execution_backends,
            "hardware_acceleration": hardware_acceleration,
            "hardware_probes": execution_backend_probes,
            "runtime_device_paths": runtime_device_paths,
            "execution_preferences": execution_preferences,
            "preferred_backend_probe": preferred_backend_probe,
            "transcode_backend_usable": transcode_backend_usable,
            "eligible": eligible,
            "eligibility_summary": eligibility_summary,
        }

    def queue_health_summary(self) -> dict[str, object]:
        if self.session_factory is None:
            return {
                "status": HealthStatus.UNKNOWN,
                "summary": "Queue state is unavailable.",
                "pending_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "manual_review_count": 0,
                "completed_count": 0,
                "oldest_pending_age_seconds": None,
                "last_completed_age_seconds": None,
                "recent_failed_count": 0,
                "recent_manual_review_count": 0,
            }

        with self.session_factory() as session:
            repository = JobRepository(session)
            counts = repository.count_by_status()
            now = datetime.now(timezone.utc)
            oldest_pending = repository.oldest_created_at_for_status(JobStatus.PENDING)
            last_completed = repository.latest_completed_at()
            recent_window = now - timedelta(hours=24)
            recent_failed_count = repository.count_recent_statuses([JobStatus.FAILED], since=recent_window)
            recent_manual_review_count = repository.count_recent_statuses(
                [JobStatus.MANUAL_REVIEW],
                since=recent_window,
            )

        pending_count = counts.get(JobStatus.PENDING.value, 0)
        running_count = counts.get(JobStatus.RUNNING.value, 0)
        failed_count = counts.get(JobStatus.FAILED.value, 0)
        manual_review_count = counts.get(JobStatus.MANUAL_REVIEW.value, 0)
        completed_count = counts.get(JobStatus.COMPLETED.value, 0) + counts.get(JobStatus.SKIPPED.value, 0)
        oldest_pending_age_seconds = age_seconds(oldest_pending, now)
        last_completed_age_seconds = age_seconds(last_completed, now)

        if running_count > 0:
            status = HealthStatus.DEGRADED
            summary = "The local worker is currently processing jobs."
        elif failed_count > 0 or manual_review_count > 0:
            status = HealthStatus.DEGRADED
            summary = "Recent job history includes failures or manual review outcomes."
        elif pending_count > 10:
            status = HealthStatus.DEGRADED
            summary = "Pending jobs are building up."
        else:
            status = HealthStatus.HEALTHY
            summary = "Queue health is within expected bounds."

        return {
            "status": status,
            "summary": summary,
            "pending_count": pending_count,
            "running_count": running_count,
            "failed_count": failed_count,
            "manual_review_count": manual_review_count,
            "completed_count": completed_count,
            "oldest_pending_age_seconds": oldest_pending_age_seconds,
            "last_completed_age_seconds": last_completed_age_seconds,
            "recent_failed_count": recent_failed_count,
            "recent_manual_review_count": recent_manual_review_count,
        }

    def status_summary(self, *, local_worker_override: Worker | None = None) -> dict[str, object]:
        local_worker = local_worker_override
        if local_worker is not None:
            execution_preferences = {
                "preferred_backend": local_worker.preferred_backend,
                "allow_cpu_fallback": local_worker.allow_cpu_fallback,
            }
        elif self.session_factory is not None:
            with self.session_factory() as session:
                local_worker_config = resolve_local_worker_configuration(
                    session,
                    config_bundle=self.config_bundle,
                    worker_name=self.local_worker_loop.worker_name,
                )
                local_worker = local_worker_config.worker
                execution_preferences = {
                    "preferred_backend": local_worker_config.preferred_backend,
                    "allow_cpu_fallback": local_worker_config.allow_cpu_fallback,
                }
        else:
            execution_preferences = SetupStateService(config_bundle=self.config_bundle).get_execution_preferences()

        runtime_probes = self._local_runtime_probes(execution_preferences=execution_preferences)
        ffmpeg = runtime_probes["ffmpeg"]
        ffprobe = runtime_probes["ffprobe"]
        queue_health = self.queue_health_summary()
        snapshot = self.local_worker_loop.status_tracker.snapshot()
        configured = local_worker is not None
        enabled = bool(
            local_worker is not None
            and local_worker.enabled
            and self.config_bundle.workers.local.enabled
        )
        available = bool(runtime_probes["eligible"] and enabled)
        telemetry = snapshot.telemetry or collect_runtime_telemetry(current_backend=snapshot.current_backend)

        if not configured:
            status = HealthStatus.UNKNOWN
            summary = "This host is not configured as a worker yet."
            configuration_state = "local_not_configured"
        elif not local_worker.enabled:
            status = HealthStatus.DEGRADED
            summary = "Local worker is configured but disabled."
            configuration_state = "local_configured_disabled"
        elif not self.config_bundle.workers.local.enabled:
            status = HealthStatus.DEGRADED
            summary = "Local worker is configured but the local worker runtime is disabled."
            configuration_state = "local_unavailable"
        elif (not runtime_probes["eligible"]) and (
            ffmpeg["status"] != HealthStatus.HEALTHY or ffprobe["status"] != HealthStatus.HEALTHY
        ):
            status = HealthStatus.FAILED
            summary = "One or more media binaries are unavailable."
            configuration_state = "local_unavailable"
        elif not runtime_probes["eligible"]:
            status = HealthStatus.DEGRADED
            summary = str(runtime_probes["eligibility_summary"])
            configuration_state = "local_degraded"
        elif not runtime_probes["transcode_backend_usable"]:
            status = HealthStatus.DEGRADED
            summary = str(runtime_probes["eligibility_summary"])
            configuration_state = "local_degraded"
        elif queue_health["status"] == HealthStatus.DEGRADED:
            status = HealthStatus.DEGRADED
            summary = "The local worker is available but queue health needs attention."
            configuration_state = "local_degraded"
        else:
            status = HealthStatus.HEALTHY
            summary = "The local worker is healthy and available."
            configuration_state = "local_healthy"

        live_capabilities = {
            "ffmpeg": bool(ffmpeg["discoverable"]),
            "ffprobe": bool(ffprobe["discoverable"]),
            "intel_qsv": any(
                bool((item.get("details") or {}).get("qsv", {}).get("usable"))
                for item in runtime_probes["hardware_probes"]
                if item["backend"] == "intel_igpu"
            ),
            "nvenc": any(
                item["backend"] == "nvidia_gpu" and item["usable_by_ffmpeg"]
                for item in runtime_probes["hardware_probes"]
            ),
            "vaapi": any(
                item["backend"] in {"intel_igpu", "amd_gpu"} and item["usable_by_ffmpeg"]
                for item in runtime_probes["hardware_probes"]
            ),
            "amd_amf": any(
                item["backend"] == "amd_gpu" and item["usable_by_ffmpeg"]
                for item in runtime_probes["hardware_probes"]
            ),
        }

        return {
            "worker_id": local_worker.id if local_worker is not None else None,
            "status": status,
            "summary": summary,
            "worker_name": local_worker.display_name if local_worker is not None else self.local_worker_loop.worker_name,
            "configured": configured,
            "configuration_state": configuration_state,
            "mode": "single-node-local",
            "local_only": True,
            "enabled": enabled,
            "available": available,
            "eligible": runtime_probes["eligible"],
            "eligibility_summary": runtime_probes["eligibility_summary"],
            "default_queue": self.config_bundle.workers.default_queue,
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "local_worker_queue": self.config_bundle.workers.local.queue,
            "execution_backends": runtime_probes["execution_backends"],
            "hardware_acceleration": runtime_probes["hardware_acceleration"],
            "hardware_probes": runtime_probes["hardware_probes"],
            "runtime_device_paths": runtime_probes["runtime_device_paths"],
            "execution_preferences": runtime_probes["execution_preferences"],
            "scratch_path": runtime_probes["scratch_path"],
            "media_paths": runtime_probes["media_paths"],
            "last_run_started_at": snapshot.last_run_started_at,
            "last_run_completed_at": snapshot.last_run_completed_at,
            "last_processed_job_id": snapshot.last_processed_job_id,
            "last_result_status": snapshot.last_result_status,
            "last_failure_message": snapshot.last_failure_message,
            "processed_jobs": snapshot.processed_jobs,
            "current_job_id": snapshot.current_job_id,
            "current_backend": snapshot.current_backend,
            "current_stage": snapshot.current_stage,
            "current_progress_percent": snapshot.current_progress_percent,
            "current_progress_updated_at": snapshot.current_progress_updated_at,
            "telemetry": telemetry,
            "capabilities": live_capabilities,
            "queue_health": queue_health,
            "self_test_available": True,
        }

    def self_test(self) -> dict[str, object]:
        started_at = datetime.now(timezone.utc)
        checks: list[dict[str, object]] = []
        ffmpeg = self.binary_status(self.config_bundle.app.media.ffmpeg_path)
        ffprobe = self.binary_status(self.config_bundle.app.media.ffprobe_path)
        checks.append(
            {
                "code": "ffmpeg_binary",
                "status": ffmpeg["status"],
                "message": ffmpeg["message"],
            }
        )
        checks.append(
            {
                "code": "ffprobe_binary",
                "status": ffprobe["status"],
                "message": ffprobe["message"],
            }
        )

        scratch_dir = Path(self.config_bundle.app.scratch_dir)
        scratch_exists = scratch_dir.exists() and scratch_dir.is_dir()
        scratch_writable = os.access(scratch_dir, os.W_OK) if scratch_exists else False
        checks.append(
            {
                "code": "scratch_path",
                "status": (
                    HealthStatus.HEALTHY
                    if scratch_exists and scratch_writable
                    else HealthStatus.FAILED
                ),
                "message": (
                    "Scratch path exists and is writable."
                    if scratch_exists and scratch_writable
                    else "Scratch path is missing or not writable."
                ),
            }
        )

        db_ok = False
        if self.session_factory is not None:
            try:
                with self.session_factory() as session:
                    session.execute(text("SELECT 1"))
                db_ok = True
            except Exception:
                db_ok = False
        checks.append(
            {
                "code": "database",
                "status": HealthStatus.HEALTHY if db_ok else HealthStatus.FAILED,
                "message": (
                    "Database connectivity check passed."
                    if db_ok
                    else "Database connectivity check failed."
                ),
            }
        )

        worker_enabled = self.config_bundle.workers.local.enabled
        checks.append(
            {
                "code": "worker_initialisation",
                "status": HealthStatus.HEALTHY if worker_enabled else HealthStatus.DEGRADED,
                "message": (
                    "Local worker loop is configured and available."
                    if worker_enabled
                    else "Local worker loop is configured but disabled."
                ),
            }
        )

        statuses = [check["status"] for check in checks]
        if any(status == HealthStatus.FAILED for status in statuses):
            status = HealthStatus.FAILED
            summary = "One or more worker self-test checks failed."
        elif any(status == HealthStatus.DEGRADED for status in statuses):
            status = HealthStatus.DEGRADED
            summary = "Worker self-test completed with warnings."
        else:
            status = HealthStatus.HEALTHY
            summary = "Worker self-test completed successfully."

        return {
            "status": status,
            "summary": summary,
            "worker_name": self.local_worker_loop.worker_name,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc),
            "checks": checks,
        }

    def register_worker(
        self,
        session: Session,
        *,
        worker_key: str,
        display_name: str,
        worker_type: str,
        registration_secret: str | None,
        pairing_token: str | None,
        capability_summary: dict | None,
        host_summary: dict | None,
        runtime_summary: dict | None,
        binary_summary: list[dict] | None,
        health_status: HealthStatus,
        health_summary: str | None,
        request: Request,
    ) -> dict[str, object]:
        if worker_type != WorkerType.REMOTE.value:
            raise ApiConflictError("Only remote workers can use the registration endpoint.")
        repository = WorkerRepository(session)
        paired_worker: Worker | None = None
        if pairing_token:
            paired_worker = repository.get_by_pairing_token_hash(
                self.worker_token_service.hash_worker_token(pairing_token)
            )
            if paired_worker is None or paired_worker.worker_type != WorkerType.REMOTE:
                self.audit_service.record_event(
                    session,
                    event_type=AuditEventType.WORKER_REGISTRATION,
                    outcome=AuditOutcome.FAILURE,
                    request=request,
                    username=worker_key,
                    details={"worker_key": worker_key, "reason": "invalid_pairing_token"},
                )
                raise ApiAuthenticationError("The worker pairing token is invalid.")
            if paired_worker.pairing_expires_at is not None:
                pairing_expires_at = paired_worker.pairing_expires_at
                if pairing_expires_at.tzinfo is None:
                    pairing_expires_at = pairing_expires_at.replace(tzinfo=timezone.utc)
                if pairing_expires_at < datetime.now(timezone.utc):
                    self.audit_service.record_event(
                        session,
                        event_type=AuditEventType.WORKER_REGISTRATION,
                        outcome=AuditOutcome.FAILURE,
                        request=request,
                        username=worker_key,
                        details={"worker_key": worker_key, "reason": "expired_pairing_token"},
                    )
                    raise ApiAuthenticationError("The worker pairing token has expired.")
            worker_key = paired_worker.worker_key
            display_name = paired_worker.display_name
        elif registration_secret != self.worker_auth_runtime.registration_secret:
            self.audit_service.record_event(
                session,
                event_type=AuditEventType.WORKER_REGISTRATION,
                outcome=AuditOutcome.FAILURE,
                request=request,
                username=worker_key,
                details={"worker_key": worker_key, "reason": "invalid_registration_secret"},
            )
            raise ApiAuthenticationError("The worker registration secret is invalid.")

        issued_at = datetime.now(timezone.utc)
        worker_token = self.worker_token_service.generate_worker_token()
        preferred_backend = (
            paired_worker.preferred_backend
            if paired_worker is not None and paired_worker.preferred_backend
            else str((runtime_summary or {}).get("preferred_backend") or "cpu_only")
        )
        allow_cpu_fallback = (
            paired_worker.allow_cpu_fallback
            if paired_worker is not None
            else bool((runtime_summary or {}).get("allow_cpu_fallback", True))
        )
        max_concurrent_jobs = (
            paired_worker.max_concurrent_jobs
            if paired_worker is not None and paired_worker.max_concurrent_jobs
            else int((capability_summary or {}).get("max_concurrent_jobs") or 1)
        )
        path_mappings = (
            copy.deepcopy(paired_worker.path_mappings)
            if paired_worker is not None
            else self._prepare_worker_path_mappings((runtime_summary or {}).get("path_mappings"))
        )
        scratch_path = (
            paired_worker.scratch_path
            if paired_worker is not None and paired_worker.scratch_path
            else str((runtime_summary or {}).get("scratch_dir") or "").strip() or None
        )
        runtime_summary_payload = self._merge_runtime_summary_preferences(
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=paired_worker.schedule_windows if paired_worker is not None else None,
            scratch_path=scratch_path,
            path_mappings=path_mappings,
            runtime_summary=runtime_summary,
        )
        worker = repository.register_remote_worker(
            worker_key=worker_key,
            display_name=display_name,
            auth_token_hash=self.worker_token_service.hash_worker_token(worker_token),
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            path_mappings=path_mappings,
            scratch_path=scratch_path,
            host_metadata=host_summary,
            capability_payload=capability_summary,
            runtime_payload=runtime_summary_payload,
            binary_payload={"binaries": binary_summary or []},
            health_status=self._to_worker_health(health_status),
            health_summary=health_summary,
            registered_at=issued_at,
        )
        self.audit_service.record_event(
            session,
            event_type=AuditEventType.WORKER_REGISTRATION,
            outcome=AuditOutcome.SUCCESS,
            request=request,
            username=worker.worker_key,
            details={"worker_id": worker.id, "worker_type": worker.worker_type.value},
        )
        return {
            "worker_id": worker.id,
            "worker_key": worker.worker_key,
            "display_name": worker.display_name,
            "worker_type": worker.worker_type.value,
            "worker_token": worker_token,
            "registration_status": worker.registration_status.value,
            "enabled": worker.enabled,
            "execution_preferences": {
                "preferred_backend": worker.preferred_backend,
                "allow_cpu_fallback": worker.allow_cpu_fallback,
            },
            "runtime_configuration": self._runtime_configuration_for_worker(worker),
            "health_status": health_status,
            "health_summary": worker.last_health_summary,
            "issued_at": issued_at,
        }

    def heartbeat(
        self,
        session: Session,
        *,
        worker: Worker,
        capability_summary: dict | None,
        host_summary: dict | None,
        runtime_summary: dict | None,
        binary_summary: list[dict] | None,
        health_status: HealthStatus,
        health_summary: str | None,
    ) -> dict[str, object]:
        heartbeat_at = datetime.now(timezone.utc)
        updated = WorkerRepository(session).record_heartbeat(
            worker,
            heartbeat_at=heartbeat_at,
            health_status=self._to_worker_health(health_status),
            health_summary=health_summary,
            capability_payload=capability_summary,
            runtime_payload=self._merge_runtime_summary_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                max_concurrent_jobs=worker.max_concurrent_jobs,
                schedule_windows=worker.schedule_windows,
                scratch_path=worker.scratch_path,
                path_mappings=worker.path_mappings,
                runtime_summary=runtime_summary,
            ),
            binary_payload={"binaries": binary_summary or []} if binary_summary is not None else None,
            host_metadata=host_summary,
        )
        return {
            "worker_id": updated.id,
            "worker_key": updated.worker_key,
            "enabled": updated.enabled,
            "registration_status": updated.registration_status.value,
            "execution_preferences": {
                "preferred_backend": updated.preferred_backend,
                "allow_cpu_fallback": updated.allow_cpu_fallback,
            },
            "runtime_configuration": self._runtime_configuration_for_worker(updated),
            "health_status": self._from_worker_health(updated.last_health_status),
            "health_summary": updated.last_health_summary,
            "heartbeat_at": heartbeat_at,
        }

    def request_job(
        self,
        session: Session,
        *,
        worker: Worker,
    ) -> dict[str, object]:
        self._ensure_remote_worker_can_execute(worker)
        repository = JobRepository(session)
        active_assignments = repository.count_active_assignments_for_worker(worker.id)
        max_concurrent_jobs = max(1, int(worker.max_concurrent_jobs or 1))
        compatible_jobs = [
            candidate
            for candidate in repository.fetch_next_pending_remote_jobs(worker)
            if job_allows_worker(
                candidate,
                worker,
                preferred_worker=(
                    WorkerRepository(session).get_by_id(candidate.preferred_worker_id)
                    if candidate.preferred_worker_id
                    else None
                ),
            )
            if self._remote_worker_can_run_job(
                worker,
                ProcessingPlan.model_validate(candidate.plan_snapshot.payload),
                source_path=(
                    candidate.tracked_file.source_path
                    if candidate.tracked_file is not None
                    else candidate.plan_snapshot.probe_snapshot.payload.get("file_path", "")
                ),
                preferred_backend=candidate.preferred_backend_override,
            )
        ]
        job = next(
            (
                candidate
                for candidate in compatible_jobs
                if candidate.assigned_worker_id == worker.id and active_assignments <= max_concurrent_jobs
            ),
            None,
        )
        if job is None and active_assignments >= max_concurrent_jobs:
            return {"status": "no_job", "job": None}
        if job is None:
            job = next((candidate for candidate in compatible_jobs if candidate.assigned_worker_id is None), None)
        if job is None:
            return {"status": "no_job", "job": None}

        payload = self._build_remote_job_payload(job, worker=worker)
        if payload is None:
            return {"status": "no_job", "job": None}

        if job.assigned_worker_id is None:
            repository.assign_worker(job, worker=worker)

        return {
            "status": "assigned",
            "job": payload,
        }

    def claim_job(
        self,
        session: Session,
        *,
        worker: Worker,
        job_id: str,
    ) -> dict[str, object]:
        self._ensure_remote_worker_can_execute(worker)
        repository = JobRepository(session)
        job = repository.get_by_id(job_id)
        if job is None:
            raise ApiNotFoundError("Job could not be found.")
        if job.status != JobStatus.PENDING:
            raise ApiConflictError("Only pending jobs can be claimed.")
        if job.assigned_worker_id not in {None, worker.id}:
            raise ApiConflictError("Job is assigned to another worker.")

        if job.assigned_worker_id is None:
            repository.assign_worker(job, worker=worker)
        requested_backend = (
            normalise_backend_preference(job.preferred_backend_override or worker.preferred_backend or "cpu_only")
            if job.job_kind != JobKind.DRY_RUN
            else None
        )
        repository.mark_running_for_worker(job, worker=worker, requested_backend=requested_backend)
        claimed_at = job.started_at or datetime.now(timezone.utc)
        return {
            "status": "claimed",
            "job_id": job.id,
            "claimed_at": claimed_at,
        }

    def submit_job_result(
        self,
        session: Session,
        *,
        worker: Worker,
        job_id: str,
        result_payload: dict[str, object],
        runtime_summary: dict | None,
    ) -> dict[str, object]:
        repository = JobRepository(session)
        tracked_files = TrackedFileRepository(session)
        job = repository.get_by_id(job_id)
        if job is None:
            raise ApiNotFoundError("Job could not be found.")
        if job.assigned_worker_id != worker.id:
            raise ApiConflictError("Job is not assigned to this worker.")
        if job.status != JobStatus.RUNNING:
            raise ApiConflictError("Only running jobs can be completed.")

        result = ExecutionResult.model_validate(result_payload)
        repository.mark_result(job, result)
        job.last_worker_id = worker.id
        job.worker_name = worker.display_name
        plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
        if job.job_kind == JobKind.DRY_RUN:
            tracked_files.update_file_state_from_plan_result(job.tracked_file, plan)
        else:
            tracked_files.update_file_state_from_execution_result(
                job.tracked_file,
                plan,
                result,
            )
            repository.apply_automatic_retry_policy(job, result)

        if runtime_summary is not None:
            worker.runtime_payload = self._merge_runtime_summary_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                max_concurrent_jobs=max(1, int(worker.max_concurrent_jobs or 1)),
                schedule_windows=worker.schedule_windows,
                scratch_path=worker.scratch_path,
                path_mappings=worker.path_mappings,
                runtime_summary=runtime_summary,
            )

        return {
            "job_id": job.id,
            "final_status": job.status.value,
            "completed_at": job.completed_at,
        }

    def report_job_failure(
        self,
        session: Session,
        *,
        worker: Worker,
        job_id: str,
        failure_message: str,
        failure_category: str,
        runtime_summary: dict | None,
    ) -> dict[str, object]:
        repository = JobRepository(session)
        tracked_files = TrackedFileRepository(session)
        job = repository.get_by_id(job_id)
        if job is None:
            raise ApiNotFoundError("Job could not be found.")
        if job.assigned_worker_id != worker.id:
            raise ApiConflictError("Job is not assigned to this worker.")
        if job.status != JobStatus.RUNNING:
            raise ApiConflictError("Only running jobs can be marked failed by a worker.")

        completed_at = datetime.now(timezone.utc)
        result = ExecutionResult(
            mode="failed",
            status="failed",
            command=[],
            output_path=None,
            final_output_path=None,
            original_backup_path=None,
            output_size_bytes=None,
            exit_code=None,
            stdout=None,
            stderr=None,
            failure_message=failure_message,
            failure_category=failure_category,
            verification=None,
            replacement=None,
            started_at=job.started_at or completed_at,
            completed_at=completed_at,
        )
        repository.mark_result(job, result)
        job.last_worker_id = worker.id
        job.worker_name = worker.display_name
        plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
        if job.job_kind == JobKind.DRY_RUN:
            tracked_files.update_file_state_from_plan_result(job.tracked_file, plan)
        else:
            tracked_files.update_file_state_from_execution_result(
                job.tracked_file,
                plan,
                result,
            )
            repository.apply_automatic_retry_policy(job, result)

        if runtime_summary is not None:
            worker.runtime_payload = self._merge_runtime_summary_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                max_concurrent_jobs=max(1, int(worker.max_concurrent_jobs or 1)),
                schedule_windows=worker.schedule_windows,
                scratch_path=worker.scratch_path,
                path_mappings=worker.path_mappings,
                runtime_summary=runtime_summary,
            )

        return {
            "job_id": job.id,
            "final_status": job.status.value,
            "completed_at": job.completed_at,
        }

    def report_job_progress(
        self,
        session: Session,
        *,
        worker: Worker,
        job_id: str,
        stage: str,
        percent: float | None,
        out_time_seconds: float | None,
        fps: float | None,
        speed: float | None,
        runtime_summary: dict | None,
    ) -> dict[str, object]:
        repository = JobRepository(session)
        job = repository.get_by_id(job_id)
        if job is None:
            raise ApiNotFoundError("Job could not be found.")
        if job.assigned_worker_id != worker.id:
            raise ApiConflictError("Job is not assigned to this worker.")
        if job.status != JobStatus.RUNNING:
            raise ApiConflictError("Only running jobs can report progress.")
        repository.record_progress(
            job,
            update=ExecutionProgressUpdate(
                stage=stage,
                percent=percent,
                out_time_seconds=out_time_seconds,
                fps=fps,
                speed=speed,
                updated_at=datetime.now(timezone.utc),
            ),
        )
        if runtime_summary is not None:
            worker.runtime_payload = self._merge_runtime_summary_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                max_concurrent_jobs=max(1, int(worker.max_concurrent_jobs or 1)),
                schedule_windows=worker.schedule_windows,
                scratch_path=worker.scratch_path,
                path_mappings=worker.path_mappings,
                runtime_summary=runtime_summary,
            )
        return {
            "job_id": job.id,
            "updated_at": job.progress_updated_at or datetime.now(timezone.utc),
        }

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

    def create_remote_onboarding(
        self,
        session: Session,
        *,
        request: Request,
        platform: str,
        display_name: str | None,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None = None,
        scratch_path: str | None = None,
        path_mappings: list[dict] | None = None,
    ) -> dict[str, object]:
        repository = WorkerRepository(session)
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(hours=24)
        pairing_token = self.worker_token_service.generate_worker_token()
        worker_key = self._build_remote_worker_key(display_name)
        try:
            cleaned_schedule = normalise_schedule_windows(schedule_windows)
        except ValueError as error:
            raise ApiConflictError(str(error)) from error
        worker = repository.create_pending_remote_worker(
            worker_key=worker_key,
            display_name=display_name or self._default_remote_display_name(platform),
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=cleaned_schedule,
            path_mappings=normalise_path_mappings(path_mappings),
            scratch_path=scratch_path or self._default_remote_scratch_path(platform),
            pairing_token_hash=self.worker_token_service.hash_worker_token(pairing_token),
            pairing_requested_at=issued_at,
            pairing_expires_at=expires_at,
            onboarding_platform=platform,
            install_dir=self._default_remote_install_dir(platform),
        )
        return {
            "worker": self._remote_worker_summary(worker, detail=True),
            "status": "pending_pairing",
            "pairing_token_expires_at": expires_at,
            "bootstrap_command": self._build_remote_bootstrap_command(
                request=request,
                platform=platform,
                worker=worker,
                pairing_token=pairing_token,
            ),
            "uninstall_command": self._build_remote_uninstall_command(platform=platform, worker=worker),
            "notes": self._remote_bootstrap_notes(platform=platform),
        }

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

    def _local_worker_inventory(self, *, worker: Worker, detail: bool = False) -> dict[str, object]:
        status = self.status_summary(local_worker_override=worker)
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
            "last_seen_at": status["last_run_completed_at"],
            "last_heartbeat_at": status["last_run_completed_at"],
            "last_registration_at": worker.created_at,
            "capability_summary": self._local_capability_summary(),
            "host_summary": {
                "hostname": local_config.host,
                "platform": None,
                "agent_version": None,
                "python_version": None,
            },
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
            item.update(
                {
                    "runtime_summary": {
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
                        "current_stage": current_stage,
                        "current_progress_percent": current_progress_percent,
                        "current_progress_updated_at": current_progress_updated_at,
                        "telemetry": status["telemetry"],
                        "last_completed_job_id": status["last_processed_job_id"],
                    },
                    "binary_summary": [
                        self._binary_inventory_item("ffmpeg", status["ffmpeg"]),
                        self._binary_inventory_item("ffprobe", status["ffprobe"]),
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

    def _ensure_remote_worker_can_execute(self, worker: Worker) -> None:
        if worker.worker_type != WorkerType.REMOTE:
            raise ApiConflictError("Only remote workers can poll for remote work.")
        if not worker.enabled:
            raise ApiConflictError("The worker is not currently enabled for execution.")
        if worker.registration_status != WorkerRegistrationStatus.REGISTERED:
            raise ApiConflictError("The worker has not completed pairing yet.")
        if worker.last_health_status == WorkerHealthStatus.FAILED:
            raise ApiConflictError("The worker last reported a failed health state.")

        capability_summary = self._clean_capability_summary(worker.capability_payload)
        binary_support = capability_summary.get("binary_support", {})
        if not binary_support.get("ffmpeg") or not binary_support.get("ffprobe"):
            raise ApiConflictError("The worker has not reported usable FFmpeg and FFprobe support.")
        if not capability_summary.get("execution_modes"):
            raise ApiConflictError("The worker has not reported any execution modes.")
        runtime_summary = self._clean_runtime_summary(worker.runtime_payload)
        scratch_status = runtime_summary.get("scratch_status")
        if isinstance(scratch_status, dict) and scratch_status.get("status") not in {None, "healthy", "unknown"}:
            raise ApiConflictError("The worker scratch path is not ready for execution.")

    def _remote_worker_can_run_job(
        self,
        worker: Worker,
        plan: ProcessingPlan,
        *,
        source_path: str,
        preferred_backend: str | None = None,
    ) -> bool:
        capability_summary = self._clean_capability_summary(worker.capability_payload)
        binary_support = capability_summary.get("binary_support", {})
        execution_modes = capability_summary.get("execution_modes", [])
        if not binary_support.get("ffmpeg") or not binary_support.get("ffprobe"):
            return False
        if not execution_modes:
            return False
        if not worker.enabled or worker.registration_status != WorkerRegistrationStatus.REGISTERED:
            return False
        if self._resolve_remote_source_path(worker, source_path) is None:
            return False
        runtime_summary = self._clean_runtime_summary(worker.runtime_payload)
        scratch_status = runtime_summary.get("scratch_status")
        if isinstance(scratch_status, dict) and scratch_status.get("status") not in {None, "healthy", "unknown"}:
            return False
        for mapping in runtime_summary.get("path_mappings", []):
            if mapping.get("validation_status") not in {None, "usable"}:
                return False
        if not plan.video.transcode_required:
            return "remux" in execution_modes or "transcode" in execution_modes

        preferred_backend = normalise_backend_preference(preferred_backend or worker.preferred_backend or "cpu_only")
        allow_cpu_fallback = bool(worker.allow_cpu_fallback)
        codec = (plan.video.target_codec or "hevc").strip().lower()
        hardware_hints = {str(item) for item in capability_summary.get("hardware_hints", [])}

        if preferred_backend == "cpu":
            return "transcode" in execution_modes

        if preferred_backend in hardware_hints and codec in {"h264", "hevc"}:
            return True

        return allow_cpu_fallback and "transcode" in execution_modes

    def _validate_local_backend_preferences(
        self,
        *,
        preferred_backend: str,
        allow_cpu_fallback: bool,
    ) -> None:
        runtime_probes = self._local_runtime_probes(
            execution_preferences={
                "preferred_backend": preferred_backend,
                "allow_cpu_fallback": allow_cpu_fallback,
            }
        )
        if preferred_backend == "cpu_only":
            return
        preferred_probe = runtime_probes.get("preferred_backend_probe")
        if preferred_probe is None:
            raise ApiConflictError("The selected local backend is not recognised.")
        if not preferred_probe["usable_by_ffmpeg"] and not allow_cpu_fallback:
            raise ApiConflictError(
                "The selected local backend is unavailable in this runtime and CPU fallback is disabled."
            )

    def _remote_worker_state(self, worker: Worker) -> str:
        if not worker.enabled:
            return "remote_disabled"
        if worker.registration_status != WorkerRegistrationStatus.REGISTERED:
            return "remote_pending_pairing"
        if worker.last_heartbeat_at is None:
            return "remote_registered"
        last_heartbeat_at = worker.last_heartbeat_at
        if last_heartbeat_at.tzinfo is None:
            last_heartbeat_at = last_heartbeat_at.replace(tzinfo=timezone.utc)
        if last_heartbeat_at < datetime.now(timezone.utc) - timedelta(minutes=5):
            return "remote_offline"
        if worker.last_health_status == WorkerHealthStatus.HEALTHY:
            return "remote_healthy"
        if worker.last_health_status == WorkerHealthStatus.FAILED:
            return "remote_degraded"
        if worker.last_health_status == WorkerHealthStatus.DEGRADED:
            return "remote_degraded"
        return "remote_registered"

    def _build_remote_worker_key(self, display_name: str | None) -> str:
        base = (display_name or "remote-worker").strip().lower()
        slug = "".join(character if character.isalnum() else "-" for character in base)
        slug = "-".join(part for part in slug.split("-") if part) or "remote-worker"
        return f"worker-{slug}-{self.worker_token_service.generate_worker_token()[:8].lower()}"

    @staticmethod
    def _default_remote_display_name(platform: str) -> str:
        return {
            "windows": "Windows worker",
            "linux": "Linux worker",
            "macos": "macOS worker",
        }.get(platform, "Remote worker")

    def _build_remote_bootstrap_command(
        self,
        *,
        request: Request,
        platform: str,
        worker: Worker,
        pairing_token: str,
    ) -> str:
        version_ref = read_version()
        if version_ref and not version_ref.startswith("v"):
            version_ref = f"v{version_ref}"
        api_base_url = self._remote_api_base_url(request)
        worker_key = worker.worker_key
        display_name = worker.display_name
        preferred_backend = worker.preferred_backend
        allow_cpu_fallback = "$true" if worker.allow_cpu_fallback else "$false"
        install_dir = worker.install_dir or self._default_remote_install_dir(platform)
        scratch_dir = worker.scratch_path or self._default_remote_scratch_path(platform)
        if platform == "windows":
            script_url = (
                f"https://raw.githubusercontent.com/RoBro92/encodr/{version_ref}/"
                "infra/scripts/install-worker-agent-windows.ps1"
            )
            return (
                "powershell -NoProfile -ExecutionPolicy Bypass -Command "
                f"\"& {{ $script = Join-Path $env:TEMP 'encodr-worker.ps1'; "
                f"Invoke-WebRequest -UseBasicParsing '{script_url}' -OutFile $script; "
                f"& $script -ServerUrl '{api_base_url}' "
                f"-WorkerKey '{worker_key}' -PairingToken '{pairing_token}' "
                f"-ReleaseRef '{version_ref}' "
                f"-DisplayName '{display_name}' -PreferredBackend '{preferred_backend}' "
                f"-AllowCpuFallback {allow_cpu_fallback} -InstallDir '{install_dir}' "
                f"-ScratchDir '{scratch_dir}' }}\""
            )

        script_url = (
            f"https://raw.githubusercontent.com/RoBro92/encodr/{version_ref}/"
            "infra/scripts/install-worker-agent-unix.sh"
        )
        platform_flag = "macos" if platform == "macos" else "linux"
        return (
            f"curl -fsSL {shlex.quote(script_url)} | sudo bash -s -- "
            f"--server-url {shlex.quote(api_base_url)} "
            f"--worker-key {shlex.quote(worker_key)} "
            f"--pairing-token {shlex.quote(pairing_token)} "
            f"--release-ref {shlex.quote(version_ref)} "
            f"--display-name {shlex.quote(display_name)} "
            f"--platform {shlex.quote(platform_flag)} "
            f"--install-dir {shlex.quote(install_dir)} "
            f"--scratch-dir {shlex.quote(scratch_dir)} "
            f"--preferred-backend {shlex.quote(preferred_backend)} "
            f"--allow-cpu-fallback {'true' if worker.allow_cpu_fallback else 'false'}"
        )

    @staticmethod
    def _remote_bootstrap_notes(*, platform: str) -> list[str]:
        notes = [
            "Run the command on the target worker host with administrator or root privileges.",
            "The worker pairs back to Encodr as a background service; no desktop app is required.",
        ]
        if platform == "windows":
            notes.append("The Windows installer creates a scheduled task that keeps the worker running in the background.")
        elif platform == "linux":
            notes.append("The Linux installer creates a systemd service named encodr-worker.")
        elif platform == "macos":
            notes.append("The macOS installer creates a launchd daemon for the worker agent.")
        return notes

    def _build_remote_job_payload(self, job: Any, *, worker: Worker) -> dict[str, object] | None:
        media_payload = copy.deepcopy(
            job.plan_snapshot.probe_snapshot.payload
            if job.plan_snapshot and job.plan_snapshot.probe_snapshot
            else {}
        )
        source_path = (
            job.tracked_file.source_path if job.tracked_file is not None else media_payload.get("file_path", "")
        )
        remapped_source = self._resolve_remote_source_path(worker, source_path)
        if remapped_source is None:
            return None
        if isinstance(media_payload, dict):
            media_payload["file_path"] = remapped_source
        return {
            "job_id": job.id,
            "tracked_file_id": job.tracked_file_id,
            "plan_snapshot_id": job.plan_snapshot_id,
            "job_kind": job.job_kind.value,
            "source_path": remapped_source,
            "plan_payload": job.plan_snapshot.payload,
            "media_payload": media_payload,
            "analysis_payload": job.analysis_payload,
            "requested_worker_type": job.requested_worker_type.value if job.requested_worker_type is not None else None,
            "assignment_state": "claimed" if job.status == JobStatus.RUNNING else "assigned",
            "assigned_worker_id": job.assigned_worker_id,
        }

    def _local_capability_summary(self) -> dict[str, object]:
        runtime_probes = self._local_runtime_probes()
        hardware_hints = [
            item["backend"]
            for item in runtime_probes["hardware_probes"]
            if item["backend"] != "cpu" and item["usable_by_ffmpeg"]
        ]
        if not hardware_hints:
            hardware_hints.append("cpu_only")
        recommended_concurrency, recommendation_reason = recommend_worker_concurrency(
            cpu_count=os.cpu_count(),
            hardware_hints=hardware_hints,
        )
        return {
            "execution_modes": runtime_probes["execution_backends"],
            "supported_video_codecs": ["h264", "hevc", "av1"] if runtime_probes["ffmpeg"]["discoverable"] else [],
            "supported_audio_codecs": [],
            "hardware_hints": hardware_hints,
            "binary_support": {
                "ffmpeg": runtime_probes["ffmpeg"]["discoverable"],
                "ffprobe": runtime_probes["ffprobe"]["discoverable"],
            },
            "max_concurrent_jobs": self.config_bundle.workers.local.max_concurrent_jobs,
            "recommended_concurrency": recommended_concurrency,
            "recommended_concurrency_reason": recommendation_reason,
            "tags": ["local"],
        }

    @staticmethod
    def _serialise_backend_probe(probe) -> dict[str, object]:
        preference_key = {
            "cpu": "cpu_only",
            "intel_igpu": "prefer_intel_igpu",
            "nvidia_gpu": "prefer_nvidia_gpu",
            "amd_gpu": "prefer_amd_gpu",
        }.get(probe.backend, probe.backend)
        return {
            "backend": probe.backend,
            "preference_key": preference_key,
            "detected": probe.detected,
            "usable_by_ffmpeg": probe.usable,
            "ffmpeg_path_verified": bool(probe.details.get("ffmpeg_path_verified", probe.usable)),
            "status": probe.status,
            "message": probe.message,
            "reason_unavailable": probe.details.get("reason_unavailable"),
            "recommended_usage": probe.details.get("recommended_usage"),
            "device_paths": probe.details.get("device_paths", []),
            "details": probe.details,
        }

    @staticmethod
    def _binary_inventory_item(name: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "name": name,
            "configured_path": payload.get("configured_path"),
            "discoverable": payload.get("discoverable"),
            "message": payload.get("message"),
        }

    @staticmethod
    def _clean_capability_summary(payload: dict | None) -> dict[str, object]:
        payload = payload or {}
        return {
            "execution_modes": payload.get("execution_modes", []),
            "supported_video_codecs": payload.get("supported_video_codecs", []),
            "supported_audio_codecs": payload.get("supported_audio_codecs", []),
            "hardware_hints": payload.get("hardware_hints", []),
            "binary_support": payload.get("binary_support", {}),
            "max_concurrent_jobs": payload.get("max_concurrent_jobs"),
            "recommended_concurrency": payload.get("recommended_concurrency"),
            "recommended_concurrency_reason": payload.get("recommended_concurrency_reason"),
            "tags": payload.get("tags", []),
        }

    @staticmethod
    def _clean_host_summary(payload: dict | None) -> dict[str, object]:
        payload = payload or {}
        return {
            "hostname": payload.get("hostname"),
            "platform": payload.get("platform"),
            "agent_version": payload.get("agent_version"),
            "python_version": payload.get("python_version"),
        }

    @staticmethod
    def _clean_runtime_summary(payload: dict | None) -> dict[str, object]:
        payload = payload or {}
        return {
            "queue": payload.get("queue"),
            "scratch_dir": payload.get("scratch_dir"),
            "scratch_status": payload.get("scratch_status"),
            "media_mounts": payload.get("media_mounts", []),
            "path_mappings": payload.get("path_mappings", []),
            "preferred_backend": payload.get("preferred_backend"),
            "allow_cpu_fallback": payload.get("allow_cpu_fallback"),
            "max_concurrent_jobs": payload.get("max_concurrent_jobs"),
            "current_job_id": payload.get("current_job_id"),
            "current_backend": payload.get("current_backend"),
            "current_stage": payload.get("current_stage"),
            "current_progress_percent": payload.get("current_progress_percent"),
            "current_progress_updated_at": payload.get("current_progress_updated_at"),
            "telemetry": payload.get("telemetry"),
            "last_completed_job_id": payload.get("last_completed_job_id"),
            "schedule_windows": payload.get("schedule_windows", []),
        }

    def _merge_runtime_summary_preferences(
        self,
        *,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        max_concurrent_jobs: int,
        schedule_windows: list[dict] | None,
        scratch_path: str | None,
        path_mappings: list[dict] | None,
        runtime_summary: dict | None,
    ) -> dict | None:
        merged = copy.deepcopy(runtime_summary or {})
        if scratch_path:
            merged["scratch_dir"] = scratch_path
            if merged.get("scratch_status") is None:
                merged["scratch_status"] = {
                    "path": scratch_path,
                    "status": "unknown",
                    "message": "Scratch validation has not been reported by the worker yet.",
                }
        merged["path_mappings"] = self._validated_path_mappings(
            path_mappings,
            remote_runtime_payload=merged.get("path_mappings"),
            validate_locally=False,
        )
        return merged | {
            "preferred_backend": preferred_backend,
            "allow_cpu_fallback": allow_cpu_fallback,
            "max_concurrent_jobs": max_concurrent_jobs,
            "schedule_windows": schedule_windows or [],
        }

    def _resolve_remote_source_path(self, worker: Worker, source_path: str) -> str | None:
        if worker.path_mappings:
            return remap_server_path(source_path, worker.path_mappings)
        runtime_summary = self._clean_runtime_summary(worker.runtime_payload)
        media_mounts = [str(item) for item in runtime_summary.get("media_mounts", []) if item]
        if not media_mounts:
            return source_path
        resolved_source = Path(source_path).expanduser().resolve().as_posix()
        for mount in media_mounts:
            try:
                resolved_mount = Path(str(mount)).expanduser().resolve().as_posix()
            except FileNotFoundError:
                resolved_mount = str(Path(str(mount)).expanduser())
            if resolved_source == resolved_mount or resolved_source.startswith(f"{resolved_mount}/"):
                return resolved_source
        # Preserve the existing shared-path remote worker model for workers that
        # have not been configured with explicit mappings yet. Once mappings are
        # configured we require them to validate cleanly, but older workers must
        # remain able to accept jobs that rely on the same visible source path.
        return source_path

    def _runtime_configuration_for_worker(self, worker: Worker) -> dict[str, object]:
        return self._clean_runtime_summary(
            self._merge_runtime_summary_preferences(
                preferred_backend=worker.preferred_backend,
                allow_cpu_fallback=worker.allow_cpu_fallback,
                max_concurrent_jobs=max(1, int(worker.max_concurrent_jobs or 1)),
                schedule_windows=worker.schedule_windows,
                scratch_path=worker.scratch_path,
                path_mappings=worker.path_mappings,
                runtime_summary=worker.runtime_payload,
            )
        )

    def _validated_path_mappings(
        self,
        path_mappings: list[dict] | None,
        *,
        remote_runtime_payload: list[dict] | None,
        validate_locally: bool,
    ) -> list[dict[str, object]]:
        configured = self._prepare_worker_path_mappings(path_mappings)
        runtime_by_worker_path = {
            str(item.get("worker_path")): item
            for item in (remote_runtime_payload or [])
            if item.get("worker_path")
        }
        items: list[dict[str, object]] = []
        for mapping in configured:
            server_marker = ensure_mapping_marker(mapping["server_path"])
            runtime_validation = runtime_by_worker_path.get(mapping["worker_path"], {})
            if validate_locally:
                runtime_validation = validate_worker_path_mapping(mapping["worker_path"])
            items.append(
                {
                    "label": mapping.get("label"),
                    "server_path": mapping["server_path"],
                    "worker_path": mapping["worker_path"],
                    "marker_relative_path": mapping.get("marker_relative_path"),
                    "validation_status": runtime_validation.get("status", server_marker["status"]),
                    "validation_message": runtime_validation.get("message", server_marker["message"]),
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "marker_server_path": server_marker.get("marker_server_path"),
                    "marker_worker_path": runtime_validation.get("marker_worker_path"),
                }
            )
        return items

    @staticmethod
    def _prepare_worker_path_mappings(path_mappings: list[dict] | None) -> list[dict]:
        return normalise_path_mappings(path_mappings)

    @staticmethod
    def _default_remote_install_dir(platform: str) -> str:
        if platform == "windows":
            return r"C:\ProgramData\EncodrWorker"
        if platform == "macos":
            return "/opt/encodr-worker"
        return "/opt/encodr-worker"

    def _default_remote_scratch_path(self, platform: str) -> str:
        install_dir = self._default_remote_install_dir(platform)
        if platform == "windows":
            return rf"{install_dir}\scratch"
        return f"{install_dir}/scratch"

    def _build_remote_uninstall_command(self, *, platform: str, worker: Worker) -> str:
        install_dir = worker.install_dir or self._default_remote_install_dir(platform)
        if platform == "windows":
            return (
                "powershell -NoProfile -ExecutionPolicy Bypass -File "
                f"\"{install_dir}\\uninstall-worker-agent.ps1\""
            )
        return f"sudo {shlex.quote(str(Path(install_dir) / 'uninstall-worker-agent.sh'))}"

    @staticmethod
    def _remote_uninstall_notes(*, platform: str) -> list[str]:
        notes = [
            "Deleting the worker in Encodr revokes its server-side token immediately.",
            "Run the uninstall command on the worker host to remove the local service and files.",
        ]
        if platform == "windows":
            notes.append("The Windows uninstall removes the scheduled task and ProgramData worker directory.")
        elif platform == "macos":
            notes.append("The macOS uninstall removes the launchd daemon and worker install directory.")
        else:
            notes.append("The Linux uninstall removes the systemd service and worker install directory.")
        return notes

    def _remote_api_base_url(self, request: Request) -> str:
        public_url = str(self.config_bundle.app.ui.public_url).rstrip("/")
        parsed = urlparse(public_url)
        scheme = parsed.scheme or request.url.scheme
        port = parsed.port
        host = parsed.hostname or request.url.hostname or "127.0.0.1"
        authority = self._remote_api_host(host)
        if port is not None:
            authority = f"{authority}:{port}"
        return f"{scheme}://{authority}{self.config_bundle.app.api.base_path}"

    def _remote_api_host(self, host: str) -> str:
        if host in {"localhost", "127.0.0.1", "::1"}:
            return self._detect_local_ip()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return host
        return host

    @staticmethod
    def _detect_local_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return str(sock.getsockname()[0])
        except OSError:
            return "127.0.0.1"

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

    @staticmethod
    def _to_worker_health(value: HealthStatus) -> WorkerHealthStatus:
        return WorkerHealthStatus(value.value)

    @staticmethod
    def _from_worker_health(value: WorkerHealthStatus) -> HealthStatus:
        return HealthStatus(value.value)


def age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds()))
