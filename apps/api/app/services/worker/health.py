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

class WorkerHealthService(WorkerBaseService):
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

        if failed_count > 0 or manual_review_count > 0:
            status = HealthStatus.DEGRADED
            summary = "Recent job history includes failures or manual review outcomes."
        elif pending_count > 10:
            status = HealthStatus.DEGRADED
            summary = "Pending jobs are building up."
        elif running_count > 0:
            status = HealthStatus.HEALTHY
            summary = "The queue is active and workers are processing jobs."
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
        elif not runtime_probes["transcode_backend_usable"] or (runtime_probes.get("backend_runtime_status") or {}).get("degraded"):
            status = HealthStatus.DEGRADED
            summary = str(runtime_probes["eligibility_summary"])
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
                item["backend"] in {"intel_igpu", "amd_gpu"}
                and bool((item.get("details") or {}).get("vaapi", {}).get("usable"))
                for item in runtime_probes["hardware_probes"]
            ),
            "amd_amf": any(
                item["backend"] == "amd_gpu" and bool((item.get("details") or {}).get("amf", {}).get("usable"))
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
            "selected_backend": (runtime_probes.get("backend_runtime_status") or {}).get("selected_backend"),
            "backend_fallback_used": (runtime_probes.get("backend_runtime_status") or {}).get("fallback_used"),
            "backend_fallback_reason": (runtime_probes.get("backend_runtime_status") or {}).get("fallback_reason"),
            "qsv_usable": (runtime_probes.get("backend_runtime_status") or {}).get("qsv_usable"),
            "qsv_unavailable_reason": (runtime_probes.get("backend_runtime_status") or {}).get("qsv_unavailable_reason"),
            "vaapi_usable": (runtime_probes.get("backend_runtime_status") or {}).get("vaapi_usable"),
            "vaapi_unavailable_reason": (runtime_probes.get("backend_runtime_status") or {}).get("vaapi_unavailable_reason"),
            "backend_diagnostic": runtime_probes.get("backend_runtime_status"),
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

