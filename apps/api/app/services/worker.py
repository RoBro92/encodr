from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.worker import HealthStatus
from app.services.audit import AuditService
from app.services.errors import ApiAuthenticationError, ApiConflictError, ApiNotFoundError
from encodr_core.config import ConfigBundle
from encodr_db.models import (
    AuditEventType,
    AuditOutcome,
    JobStatus,
    User,
    Worker,
    WorkerHealthStatus,
    WorkerRegistrationStatus,
    WorkerType,
)
from encodr_db.repositories import JobRepository, WorkerRepository
from encodr_db.runtime import LocalWorkerLoop, WorkerRunSummary


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
        resolved = Path(configured_path)
        if resolved.is_absolute():
            exists = resolved.exists()
            executable = exists and os.access(resolved, os.X_OK)
            discoverable = executable
        else:
            resolved_command = shutil.which(str(configured_path))
            exists = resolved_command is not None
            executable = exists
            discoverable = exists

        if discoverable:
            status = HealthStatus.HEALTHY
            message = "Binary is discoverable and executable."
        else:
            status = HealthStatus.FAILED
            message = "Binary is not discoverable or executable."

        return {
            "configured_path": str(configured_path),
            "exists": exists,
            "executable": executable,
            "discoverable": discoverable,
            "status": status,
            "message": message,
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

    def status_summary(self) -> dict[str, object]:
        ffmpeg = self.binary_status(self.config_bundle.app.media.ffmpeg_path)
        ffprobe = self.binary_status(self.config_bundle.app.media.ffprobe_path)
        queue_health = self.queue_health_summary()
        snapshot = self.local_worker_loop.status_tracker.snapshot()
        enabled = self.config_bundle.workers.local.enabled
        binaries_healthy = (
            ffmpeg["status"] == HealthStatus.HEALTHY and ffprobe["status"] == HealthStatus.HEALTHY
        )
        available = enabled and binaries_healthy

        if not enabled:
            status = HealthStatus.DEGRADED
            summary = "The local worker is disabled in configuration."
        elif not binaries_healthy:
            status = HealthStatus.FAILED
            summary = "One or more media binaries are unavailable."
        elif queue_health["status"] == HealthStatus.DEGRADED:
            status = HealthStatus.DEGRADED
            summary = "The local worker is available but queue health needs attention."
        else:
            status = HealthStatus.HEALTHY
            summary = "The local worker is healthy and available."

        return {
            "status": status,
            "summary": summary,
            "worker_name": self.local_worker_loop.worker_name,
            "mode": "single-node-local",
            "local_only": True,
            "enabled": enabled,
            "available": available,
            "default_queue": self.config_bundle.workers.default_queue,
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "local_worker_queue": self.config_bundle.workers.local.queue,
            "last_run_started_at": snapshot.last_run_started_at,
            "last_run_completed_at": snapshot.last_run_completed_at,
            "last_processed_job_id": snapshot.last_processed_job_id,
            "last_result_status": snapshot.last_result_status,
            "last_failure_message": snapshot.last_failure_message,
            "processed_jobs": snapshot.processed_jobs,
            "capabilities": self.config_bundle.workers.local.capabilities.model_dump(mode="json"),
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
        registration_secret: str,
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
        if registration_secret != self.worker_auth_runtime.registration_secret:
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
        worker = WorkerRepository(session).register_remote_worker(
            worker_key=worker_key,
            display_name=display_name,
            auth_token_hash=self.worker_token_service.hash_worker_token(worker_token),
            host_metadata=host_summary,
            capability_payload=capability_summary,
            runtime_payload=runtime_summary,
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
            runtime_payload=runtime_summary,
            binary_payload={"binaries": binary_summary or []} if binary_summary is not None else None,
            host_metadata=host_summary,
        )
        return {
            "worker_id": updated.id,
            "worker_key": updated.worker_key,
            "enabled": updated.enabled,
            "registration_status": updated.registration_status.value,
            "health_status": self._from_worker_health(updated.last_health_status),
            "health_summary": updated.last_health_summary,
            "heartbeat_at": heartbeat_at,
        }

    def list_worker_inventory(
        self,
        session: Session,
        *,
        include_disabled: bool = True,
    ) -> list[dict[str, object]]:
        repository = WorkerRepository(session)
        remote_workers = repository.list_workers(enabled=None if include_disabled else True)
        items = [self._local_worker_inventory()]
        items.extend(self._remote_worker_summary(worker) for worker in remote_workers)
        items.sort(
            key=lambda item: (
                0 if item["worker_type"] == WorkerType.LOCAL.value else 1,
                item["display_name"].lower(),
            )
        )
        return items

    def get_worker_inventory_item(self, session: Session, *, worker_id: str) -> dict[str, object]:
        if worker_id == self.config_bundle.workers.local.id:
            return self._local_worker_inventory(detail=True)

        repository = WorkerRepository(session)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        return self._remote_worker_summary(worker, detail=True)

    def set_remote_worker_enabled(
        self,
        session: Session,
        *,
        worker_id: str,
        enabled: bool,
        actor: User,
        request: Request,
    ) -> dict[str, object]:
        if worker_id == self.config_bundle.workers.local.id:
            raise ApiConflictError("The local worker is configuration-driven and cannot be toggled here.")

        repository = WorkerRepository(session)
        worker = repository.get_by_id(worker_id) or repository.get_by_key(worker_id)
        if worker is None:
            raise ApiNotFoundError("Worker could not be found.")
        if worker.worker_type != WorkerType.REMOTE:
            raise ApiConflictError("Only remote worker records can be enabled or disabled here.")

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
        return self._remote_worker_summary(worker, detail=True)

    def _local_worker_inventory(self, *, detail: bool = False) -> dict[str, object]:
        status = self.status_summary()
        local_config = self.config_bundle.workers.local
        item: dict[str, object] = {
            "id": local_config.id,
            "worker_key": local_config.id,
            "display_name": self.local_worker_loop.worker_name,
            "worker_type": WorkerType.LOCAL.value,
            "source": "projected_local",
            "enabled": status["enabled"],
            "registration_status": (
                WorkerRegistrationStatus.REGISTERED.value
                if status["enabled"]
                else WorkerRegistrationStatus.DISABLED.value
            ),
            "health_status": status["status"],
            "health_summary": status["summary"],
            "last_seen_at": status["last_run_completed_at"],
            "last_heartbeat_at": status["last_run_completed_at"],
            "last_registration_at": None,
            "capability_summary": self._local_capability_summary(),
            "host_summary": {
                "hostname": local_config.host,
                "platform": None,
                "agent_version": None,
                "python_version": None,
            },
            "pending_assignment_count": status["queue_health"]["pending_count"],
            "last_completed_job_id": status["last_processed_job_id"],
        }
        if detail:
            item.update(
                {
                    "runtime_summary": {
                        "queue": local_config.queue,
                        "scratch_dir": str(local_config.scratch_dir),
                        "media_mounts": [str(path) for path in local_config.media_mounts],
                        "last_completed_job_id": status["last_processed_job_id"],
                    },
                    "binary_summary": [
                        self._binary_inventory_item("ffmpeg", status["ffmpeg"]),
                        self._binary_inventory_item("ffprobe", status["ffprobe"]),
                    ],
                    "assigned_job_ids": [],
                    "last_processed_job_id": status["last_processed_job_id"],
                    "recent_failure_message": status["last_failure_message"],
                }
            )
        return item

    def _remote_worker_summary(self, worker: Worker, *, detail: bool = False) -> dict[str, object]:
        runtime_payload = worker.runtime_payload or {}
        binary_payload = worker.binary_payload or {}
        item: dict[str, object] = {
            "id": worker.id,
            "worker_key": worker.worker_key,
            "display_name": worker.display_name,
            "worker_type": worker.worker_type.value,
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
            "pending_assignment_count": len(worker.assigned_jobs),
            "last_completed_job_id": runtime_payload.get("last_completed_job_id"),
        }
        if detail:
            item.update(
                {
                    "runtime_summary": self._clean_runtime_summary(runtime_payload),
                    "binary_summary": binary_payload.get("binaries", []),
                    "assigned_job_ids": [job.id for job in worker.assigned_jobs],
                    "last_processed_job_id": runtime_payload.get("last_completed_job_id"),
                    "recent_failure_message": worker.last_health_summary if worker.last_health_status == WorkerHealthStatus.FAILED else None,
                }
            )
        return item

    def _local_capability_summary(self) -> dict[str, object]:
        capabilities = self.config_bundle.workers.local.capabilities
        hardware_hints = []
        if capabilities.intel_qsv:
            hardware_hints.append("intel_qsv")
        if capabilities.vaapi:
            hardware_hints.append("vaapi")
        if capabilities.nvenc:
            hardware_hints.append("nvenc")
        if capabilities.amd_amf:
            hardware_hints.append("amd_amf")
        if not hardware_hints:
            hardware_hints.append("cpu_only")
        return {
            "execution_modes": ["remux", "transcode"] if capabilities.ffmpeg else [],
            "supported_video_codecs": ["hevc"],
            "supported_audio_codecs": [],
            "hardware_hints": hardware_hints,
            "binary_support": {
                "ffmpeg": capabilities.ffmpeg,
                "ffprobe": capabilities.ffprobe,
            },
            "max_concurrent_jobs": self.config_bundle.workers.local.max_concurrent_jobs,
            "tags": ["local"],
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
            "media_mounts": payload.get("media_mounts", []),
            "last_completed_job_id": payload.get("last_completed_job_id"),
        }

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
