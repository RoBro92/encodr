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

def _worker_log_extra(event: str, **fields: object) -> dict[str, object]:
    return {
        "event": event,
        **{key: value for key, value in fields.items() if value is not None},
    }


def age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds()))
class WorkerBaseService:
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
            serialise_backend_probe(item)
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
        backend_runtime_status = resolve_backend_runtime_status(
            preferred_backend,
            execution_backend_probes,
            allow_cpu_fallback=bool(execution_preferences["allow_cpu_fallback"]),
            cpu_available=ffmpeg["status"] == HealthStatus.HEALTHY,
        )
        preferred_backend_probe = next(
            (item for item in execution_backend_probes if backend_probe_matches_preference(item, preferred_backend)),
            None,
        )
        transcode_backend_usable = bool(backend_runtime_status["transcode_backend_usable"])
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
        elif not transcode_backend_usable or backend_runtime_status.get("degraded"):
            eligibility_summary = str(
                backend_runtime_status.get("message")
                or "The preferred transcode backend is unavailable. Remux jobs can still run, but transcodes will stay pending."
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
            "backend_runtime_status": backend_runtime_status,
            "eligible": eligible,
            "eligibility_summary": eligibility_summary,
        }

    @staticmethod
    def _local_worker_runtime_payload_is_fresh(worker: Worker | None) -> bool:
        if worker is None or worker.last_heartbeat_at is None:
            return False
        heartbeat = worker.last_heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        if heartbeat < datetime.now(timezone.utc) - timedelta(minutes=5):
            return False
        runtime_payload = worker.runtime_payload or {}
        return runtime_payload.get("capability_source") == LOCAL_WORKER_CAPABILITY_SOURCE

    @staticmethod
    def _local_runtime_probes_from_worker_payload(
        worker: Worker,
        *,
        execution_preferences: dict[str, object],
    ) -> dict[str, object] | None:
        runtime_payload = worker.runtime_payload or {}
        if runtime_payload.get("capability_source") != LOCAL_WORKER_CAPABILITY_SOURCE:
            return None
        hardware_probes = list(runtime_payload.get("hardware_probes") or [])
        preferred_backend = str(execution_preferences["preferred_backend"])
        preferred_backend_probe = next(
            (item for item in hardware_probes if backend_probe_matches_preference(item, preferred_backend)),
            None,
        )
        backend_runtime_status = resolve_backend_runtime_status(
            preferred_backend,
            hardware_probes,
            allow_cpu_fallback=bool(execution_preferences["allow_cpu_fallback"]),
            cpu_available=bool((runtime_payload.get("ffmpeg") or {}).get("discoverable", True)),
        )
        return {
            "ffmpeg": runtime_payload.get("ffmpeg") or {},
            "ffprobe": runtime_payload.get("ffprobe") or {},
            "scratch_path": runtime_payload.get("scratch_status") or {},
            "media_paths": list(runtime_payload.get("media_paths") or []),
            "execution_backends": list(runtime_payload.get("execution_backends") or []),
            "hardware_acceleration": list(runtime_payload.get("hardware_acceleration") or []),
            "hardware_probes": hardware_probes,
            "runtime_device_paths": list(runtime_payload.get("runtime_device_paths") or []),
            "execution_preferences": execution_preferences,
            "preferred_backend_probe": preferred_backend_probe,
            "transcode_backend_usable": bool(runtime_payload.get("transcode_backend_usable", backend_runtime_status["transcode_backend_usable"])),
            "backend_runtime_status": runtime_payload.get("backend_diagnostic") or backend_runtime_status,
            "eligible": bool(runtime_payload.get("eligible")),
            "eligibility_summary": str(runtime_payload.get("eligibility_summary") or "The local worker runtime has not reported eligibility."),
        }

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

    def _local_capability_summary(self) -> dict[str, object]:
        runtime_probes = self._local_runtime_probes()
        hardware_hints = hardware_hints_from_backend_probes(runtime_probes["hardware_probes"])
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
    def _binary_inventory_item(name: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "name": name,
            "configured_path": payload.get("configured_path"),
            "resolved_path": payload.get("resolved_path"),
            "exists": payload.get("exists"),
            "executable": payload.get("executable"),
            "discoverable": payload.get("discoverable"),
            "status": payload.get("status"),
            "message": payload.get("message"),
            "which": payload.get("which"),
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
            "hardware_probes": payload.get("hardware_probes", []),
            "capability_source": payload.get("capability_source"),
            "capability_checked_at": payload.get("capability_checked_at"),
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
        return clean_runtime_summary_payload(payload)

    def _runtime_payload_for_worker(self, worker: Worker, *, runtime_summary: dict | None) -> dict[str, object]:
        return self._merge_runtime_summary_preferences(
            preferred_backend=worker.preferred_backend,
            allow_cpu_fallback=worker.allow_cpu_fallback,
            max_concurrent_jobs=max(1, int(worker.max_concurrent_jobs or 1)),
            schedule_windows=worker.schedule_windows,
            scratch_path=worker.scratch_path,
            path_mappings=worker.path_mappings,
            runtime_summary=runtime_summary,
        )

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
        runtime_payload = copy.deepcopy(runtime_summary or {})
        validated_path_mappings = self._validated_path_mappings(
            path_mappings,
            remote_runtime_payload=runtime_payload.get("path_mappings"),
            validate_locally=False,
        )
        return merge_runtime_summary_preferences(
            runtime_payload,
            preferred_backend=preferred_backend,
            allow_cpu_fallback=allow_cpu_fallback,
            max_concurrent_jobs=max_concurrent_jobs,
            schedule_windows=schedule_windows,
            scratch_path=scratch_path,
            path_mappings=validated_path_mappings,
        )

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
        return self._clean_runtime_summary(self._runtime_payload_for_worker(worker, runtime_summary=worker.runtime_payload))

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
    def _to_worker_health(value: HealthStatus) -> WorkerHealthStatus:
        return WorkerHealthStatus(value.value)

    @staticmethod
    def _from_worker_health(value: WorkerHealthStatus) -> HealthStatus:
        return HealthStatus(value.value)

