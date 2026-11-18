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

class WorkerJobService(WorkerBaseService):
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
                if candidate.assigned_worker_id == worker.id and active_assignments < max_concurrent_jobs
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
            logger.debug(
                "remote worker poll returned no compatible job",
                extra=_worker_log_extra(
                    "remote_worker_job_poll_empty",
                    worker_id=worker.id,
                    worker_key=worker.worker_key,
                    status="no_job",
                ),
            )
            return {"status": "no_job", "job": None}

        logger.info(
            "remote worker job assigned",
            extra=_worker_log_extra(
                "remote_worker_job_assigned",
                worker_id=worker.id,
                worker_key=worker.worker_key,
                job_id=job.id,
                tracked_file_id=job.tracked_file_id,
                file_id=job.tracked_file_id,
                status="assigned",
            ),
        )
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
        if not job_allows_worker(
            job,
            worker,
            preferred_worker=(
                WorkerRepository(session).get_by_id(job.preferred_worker_id)
                if job.preferred_worker_id
                else None
            ),
        ):
            raise ApiConflictError("Job is not eligible for this worker.")
        plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
        source_path = (
            job.tracked_file.source_path
            if job.tracked_file is not None
            else job.plan_snapshot.probe_snapshot.payload.get("file_path", "")
        )
        if not self._remote_worker_can_run_job(
            worker,
            plan,
            source_path=source_path,
            preferred_backend=job.preferred_backend_override,
        ):
            raise ApiConflictError("Job is not compatible with this worker.")

        requested_backend = (
            normalise_backend_preference(job.preferred_backend_override or worker.preferred_backend or "cpu_only")
            if job.job_kind != JobKind.DRY_RUN
            else None
        )
        claimed_job = repository.claim_pending_for_worker(
            job.id,
            worker=worker,
            requested_backend=requested_backend,
            max_running_assignments=max(1, int(worker.max_concurrent_jobs or 1)),
        )
        if claimed_job is None:
            raise ApiConflictError("Job is no longer eligible to be claimed.")
        claimed_at = claimed_job.started_at or datetime.now(timezone.utc)
        logger.info(
            "remote worker job claimed",
            extra=_worker_log_extra(
                "remote_worker_job_claimed",
                worker_id=worker.id,
                worker_key=worker.worker_key,
                job_id=claimed_job.id,
                tracked_file_id=claimed_job.tracked_file_id,
                file_id=claimed_job.tracked_file_id,
                status="claimed",
                requested_backend=requested_backend,
            ),
        )
        return {
            "status": "claimed",
            "job_id": claimed_job.id,
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
        try:
            result = self._normalise_remote_execution_result_paths(worker=worker, result=result)
        except ApiValidationError as error:
            result = self._failed_untrusted_remote_result(job=job, result=result, message=str(error))
        if job.cancellation_requested_at is not None and result.status not in {"cancelled", "failed"}:
            if not self._result_completed_replacement(result):
                result = ExecutionResult(
                    mode="cancelled",
                    status="cancelled",
                    command=result.command,
                    output_path=result.output_path,
                    final_output_path=result.final_output_path,
                    original_backup_path=result.original_backup_path,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    failure_message=(
                        "Remote worker result arrived after cancellation was requested before "
                        "verified replacement completed. The original file was not marked processed."
                    ),
                    failure_category="cancelled_by_operator",
                    requested_backend=result.requested_backend,
                    actual_backend=result.actual_backend,
                    actual_accelerator=result.actual_accelerator,
                    backend_fallback_used=result.backend_fallback_used,
                    backend_selection_reason=result.backend_selection_reason,
                    verification=result.verification,
                    replacement=result.replacement,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
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
            worker.runtime_payload = self._runtime_payload_for_worker(worker, runtime_summary=runtime_summary)

        log_extra = _worker_log_extra(
            "remote_worker_job_result_received",
            worker_id=worker.id,
            worker_key=worker.worker_key,
            job_id=job.id,
            tracked_file_id=job.tracked_file_id,
            file_id=job.tracked_file_id,
            status=job.status.value,
            failure_category=job.failure_category,
            failure_message=job.failure_message,
            requested_backend=result.requested_backend,
            actual_backend=result.actual_backend,
            actual_accelerator=result.actual_accelerator,
            backend_fallback_used=result.backend_fallback_used,
        )
        if job.status == JobStatus.FAILED:
            logger.error("remote worker result failed job", extra=log_extra)
        else:
            logger.info("remote worker result accepted", extra=log_extra)
        return {
            "job_id": job.id,
            "final_status": job.status.value,
            "completed_at": job.completed_at,
        }

    def _normalise_remote_execution_result_paths(
        self,
        *,
        worker: Worker,
        result: ExecutionResult,
    ) -> ExecutionResult:
        roots = configured_path_roots(self.config_bundle)
        if worker.scratch_path:
            roots = path_roots_with_extra_scratch_roots(roots, [worker.scratch_path])
        mappings = worker.path_mappings or []
        output_path = validate_output_path(
            remap_worker_path_to_server_path(result.output_path, mappings),
            roots,
            label="output_path",
        )
        final_output_path = validate_final_output_path(
            remap_worker_path_to_server_path(result.final_output_path, mappings),
            roots,
            label="final_output_path",
        )
        original_backup_path = validate_backup_path(
            remap_worker_path_to_server_path(result.original_backup_path, mappings),
            roots,
            label="original_backup_path",
        )

        replacement = result.replacement
        if replacement is not None:
            replacement_details = remap_worker_payload_paths(replacement.details, mappings)
            replacement_details = validate_replacement_payload_paths(
                replacement_details,
                roots,
                label="replacement.details",
            )
            replacement = replacement.model_copy(
                update={
                    "final_output_path": validate_final_output_path(
                        remap_worker_path_to_server_path(replacement.final_output_path, mappings),
                        roots,
                        label="replacement.final_output_path",
                    ),
                    "original_backup_path": validate_backup_path(
                        remap_worker_path_to_server_path(replacement.original_backup_path, mappings),
                        roots,
                        label="replacement.original_backup_path",
                    ),
                    "details": replacement_details,
                }
            )

        return result.model_copy(
            update={
                "output_path": output_path,
                "final_output_path": final_output_path,
                "original_backup_path": original_backup_path,
                "replacement": replacement,
            }
        )

    @staticmethod
    def _failed_untrusted_remote_result(
        *,
        job: Job,
        result: ExecutionResult,
        message: str,
    ) -> ExecutionResult:
        completed_at = datetime.now(timezone.utc)
        return ExecutionResult(
            mode="failed",
            status="failed",
            command=result.command,
            output_path=None,
            final_output_path=None,
            original_backup_path=None,
            input_size_bytes=result.input_size_bytes,
            output_size_bytes=None,
            space_saved_bytes=None,
            video_input_size_bytes=result.video_input_size_bytes,
            video_output_size_bytes=None,
            video_space_saved_bytes=None,
            source_video_bitrate_bps=result.source_video_bitrate_bps,
            output_video_bitrate_bps=None,
            non_video_space_saved_bytes=None,
            compression_reduction_percent=None,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            failure_message=f"Remote worker result rejected: {message}",
            failure_category="untrusted_worker_result_path",
            requested_backend=result.requested_backend,
            actual_backend=result.actual_backend,
            actual_accelerator=result.actual_accelerator,
            backend_fallback_used=result.backend_fallback_used,
            backend_selection_reason=result.backend_selection_reason,
            analysis_payload=result.analysis_payload,
            verification=None,
            replacement=None,
            started_at=result.started_at or job.started_at or completed_at,
            completed_at=completed_at,
        )

    @staticmethod
    def _result_completed_replacement(result: ExecutionResult) -> bool:
        if result.status != "completed" or result.replacement is None:
            return False
        replacement_status = getattr(result.replacement.status, "value", result.replacement.status)
        return replacement_status == "succeeded" and result.final_output_path is not None

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
            worker.runtime_payload = self._runtime_payload_for_worker(worker, runtime_summary=runtime_summary)

        logger.error(
            "remote worker reported job failure",
            extra=_worker_log_extra(
                "remote_worker_job_failure_reported",
                worker_id=worker.id,
                worker_key=worker.worker_key,
                job_id=job.id,
                tracked_file_id=job.tracked_file_id,
                file_id=job.tracked_file_id,
                status=job.status.value,
                failure_category=failure_category,
                reason=failure_message,
            ),
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
            worker.runtime_payload = self._runtime_payload_for_worker(worker, runtime_summary=runtime_summary)
        logger.debug(
            "remote worker progress reported",
            extra=_worker_log_extra(
                "remote_worker_job_progress_reported",
                worker_id=worker.id,
                worker_key=worker.worker_key,
                job_id=job.id,
                tracked_file_id=job.tracked_file_id,
                file_id=job.tracked_file_id,
                status=job.status.value,
                stage=stage,
                percent=percent,
                out_time_seconds=out_time_seconds,
                fps=fps,
                speed=speed,
            ),
        )
        return {
            "job_id": job.id,
            "updated_at": job.progress_updated_at or datetime.now(timezone.utc),
            "cancellation_requested": job.cancellation_requested_at is not None,
            "cancellation_reason": job.cancellation_reason,
        }

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

        preferred_backend = preferred_backend or worker.preferred_backend or "cpu_only"
        allow_cpu_fallback = bool(worker.allow_cpu_fallback)
        codec = (plan.video.target_codec or "hevc").strip().lower()
        if codec not in {"h264", "hevc", "av1"}:
            return False
        backend_status = resolve_backend_runtime_status(
            preferred_backend,
            list(capability_summary.get("hardware_probes") or []),
            allow_cpu_fallback=allow_cpu_fallback,
            cpu_available="transcode" in execution_modes,
        )
        return bool(backend_status["transcode_backend_usable"]) and "transcode" in execution_modes

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
            "plan_payload": self._plan_payload_for_job(job),
            "media_payload": media_payload,
            "analysis_payload": job.analysis_payload,
            "requested_worker_type": job.requested_worker_type.value if job.requested_worker_type is not None else None,
            "assignment_state": "claimed" if job.status == JobStatus.RUNNING else "assigned",
            "assigned_worker_id": job.assigned_worker_id,
        }

    @staticmethod
    def _plan_payload_for_job(job: Any) -> dict:
        payload = copy.deepcopy(job.plan_snapshot.payload)
        replace = payload.get("replace")
        if isinstance(replace, dict):
            policy = str(getattr(job, "backup_policy", "keep") or "keep").strip().lower()
            if policy in {"delete_after_success", "no_backup", "delete_backup_after_success"}:
                replace["delete_replaced_source"] = True
            elif policy in {"keep", "keep_backup", "keep_for_1_day", "keep_for_one_day"}:
                replace["delete_replaced_source"] = False
            else:
                replace["delete_replaced_source"] = bool(getattr(job, "delete_replaced_source", False))
        return payload

