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

class WorkerRegistrationService(WorkerBaseService):
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
                repository.mark_auth_failed(
                    worker_key,
                    reason="invalid pairing token.",
                    failed_at=datetime.now(timezone.utc),
                )
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
                    repository.mark_auth_failed(
                        paired_worker.worker_key,
                        reason="expired pairing token.",
                        failed_at=datetime.now(timezone.utc),
                    )
                    raise ApiAuthenticationError("The worker pairing token has expired.")
            worker_key = paired_worker.worker_key
            display_name = paired_worker.display_name
        elif registration_secret != self.worker_auth_runtime.registration_secret:
            repository.mark_auth_failed(
                worker_key,
                reason="invalid registration secret.",
                failed_at=datetime.now(timezone.utc),
            )
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
        preferred_backend = coerce_backend_preference(
            paired_worker.preferred_backend
            if paired_worker is not None and paired_worker.preferred_backend
            else (runtime_summary or {}).get("preferred_backend")
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
            runtime_payload=self._runtime_payload_for_worker(worker, runtime_summary=runtime_summary),
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
            "pairing_token": pairing_token,
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
                "$pairingToken = Read-Host -Prompt 'Encodr pairing token'; "
                f"& $script -ServerUrl '{api_base_url}' "
                f"-WorkerKey '{worker_key}' -PairingToken $pairingToken "
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
            f"tmp_script=$(mktemp) && curl -fsSL {shlex.quote(script_url)} -o \"$tmp_script\" && "
            "read -rsp 'Encodr pairing token: ' ENCODR_PAIRING_TOKEN && echo && "
            'printf %s "$ENCODR_PAIRING_TOKEN" | sudo bash "$tmp_script" '
            f"--server-url {shlex.quote(api_base_url)} "
            f"--worker-key {shlex.quote(worker_key)} "
            "--pairing-token-stdin "
            f"--release-ref {shlex.quote(version_ref)} "
            f"--display-name {shlex.quote(display_name)} "
            f"--platform {shlex.quote(platform_flag)} "
            f"--install-dir {shlex.quote(install_dir)} "
            f"--scratch-dir {shlex.quote(scratch_dir)} "
            f"--preferred-backend {shlex.quote(preferred_backend)} "
            f"--allow-cpu-fallback {'true' if worker.allow_cpu_fallback else 'false'}; "
            'rm -f "$tmp_script"; unset ENCODR_PAIRING_TOKEN'
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

