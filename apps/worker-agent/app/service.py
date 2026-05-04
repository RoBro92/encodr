from __future__ import annotations

import json
import inspect
import logging
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.capabilities import (
    build_binary_summary,
    build_capability_summary,
    build_host_summary,
    build_worker_health,
    build_runtime_summary,
    probe_worker_backends,
)
from app.client import WorkerAgentHttpError, WorkerApiClient
from app.config import WorkerAgentSettings
from app.execution import RemoteExecutionService
from encodr_core.execution import ExecutionProgressUpdate
from encodr_shared import clean_runtime_summary_payload, coerce_backend_preference, collect_runtime_telemetry

logger = logging.getLogger("encodr.worker_agent.service")


def _worker_log_extra(event: str, **fields: object) -> dict[str, object]:
    return {
        "event": event,
        "diagnostic_type": "worker_runtime",
        **{key: value for key, value in fields.items() if value is not None},
    }


@dataclass(frozen=True, slots=True)
class WorkerSession:
    worker_id: str
    worker_key: str
    worker_token: str
    preferred_backend: str
    allow_cpu_fallback: bool
    runtime_configuration: dict[str, object]


class WorkerAgentService:
    def __init__(
        self,
        *,
        settings: WorkerAgentSettings,
        api_client: WorkerApiClient,
        execution_service: RemoteExecutionService | None = None,
    ) -> None:
        self.settings = settings
        self.api_client = api_client
        self.execution_service = execution_service or RemoteExecutionService(settings=settings)
        self._pairing_token_available = bool(settings.pairing_token)

    def load_worker_token(self) -> str | None:
        if self.settings.worker_token:
            return self.settings.worker_token
        if self.settings.worker_token_file and self.settings.worker_token_file.exists():
            return self.settings.worker_token_file.read_text(encoding="utf-8").strip() or None
        return None

    def store_worker_token(self, token: str) -> None:
        if self.settings.worker_token_file is None:
            return
        self.settings.worker_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.worker_token_file.write_text(token, encoding="utf-8")
        self.settings.worker_token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def clear_stored_worker_token(self) -> None:
        if self.settings.worker_token_file is None:
            return
        try:
            self.settings.worker_token_file.unlink()
        except FileNotFoundError:
            return

    def load_runtime_configuration(self) -> dict[str, object]:
        if self.settings.runtime_config_file is None or not self.settings.runtime_config_file.exists():
            return {}
        try:
            return json.loads(self.settings.runtime_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def store_runtime_configuration(self, payload: dict | None) -> None:
        if self.settings.runtime_config_file is None or payload is None:
            return
        self.settings.runtime_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.runtime_config_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.settings.runtime_config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def build_registration_payload(self) -> dict:
        runtime_configuration = self.load_runtime_configuration()
        ffmpeg_probe, backend_probes = probe_worker_backends(self.settings)
        health_status, health_summary = build_worker_health(
            self.settings,
            runtime_configuration=runtime_configuration,
            backend_probes=backend_probes,
            ffmpeg_probe=ffmpeg_probe,
        )
        return {
            "registration_secret": self.settings.registration_secret,
            "pairing_token": self.settings.pairing_token,
            "worker_key": self.settings.worker_key,
            "display_name": self.settings.display_name,
            "worker_type": "remote",
            "capability_summary": build_capability_summary(
                self.settings,
                runtime_configuration=runtime_configuration,
                backend_probes=backend_probes,
                ffmpeg_probe=ffmpeg_probe,
            ),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(
                self.settings,
                runtime_configuration=runtime_configuration,
                backend_probes=backend_probes,
                ffmpeg_probe=ffmpeg_probe,
            ),
            "binary_summary": build_binary_summary(self.settings),
            "health_status": health_status,
            "health_summary": health_summary,
        }

    def build_heartbeat_payload(self) -> dict:
        runtime_configuration = self.load_runtime_configuration()
        ffmpeg_probe, backend_probes = probe_worker_backends(self.settings)
        health_status, health_summary = build_worker_health(
            self.settings,
            runtime_configuration=runtime_configuration,
            backend_probes=backend_probes,
            ffmpeg_probe=ffmpeg_probe,
        )
        return {
            "capability_summary": build_capability_summary(
                self.settings,
                runtime_configuration=runtime_configuration,
                backend_probes=backend_probes,
                ffmpeg_probe=ffmpeg_probe,
            ),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(
                self.settings,
                runtime_configuration=runtime_configuration,
                backend_probes=backend_probes,
                ffmpeg_probe=ffmpeg_probe,
            ),
            "binary_summary": build_binary_summary(self.settings),
            "health_status": health_status,
            "health_summary": health_summary,
        }

    def register(self) -> WorkerSession:
        if not self.settings.registration_secret and not self.settings.pairing_token:
            raise RuntimeError("A pairing token or registration secret is required when no worker token is configured.")
        response = self.api_client.register(self.build_registration_payload())
        worker_token = str(response["worker_token"])
        self.store_worker_token(worker_token)
        if self.settings.pairing_token:
            self._pairing_token_available = False
        runtime_configuration = self._resolve_runtime_configuration(response)
        self.store_runtime_configuration(runtime_configuration)
        execution_preferences = self._resolve_execution_preferences(response)
        return WorkerSession(
            worker_id=str(response["worker_id"]),
            worker_key=str(response["worker_key"]),
            worker_token=worker_token,
            preferred_backend=execution_preferences["preferred_backend"],
            allow_cpu_fallback=execution_preferences["allow_cpu_fallback"],
            runtime_configuration=runtime_configuration,
        )

    def ensure_registered(self) -> WorkerSession:
        worker_token = self.load_worker_token()
        if worker_token:
            return WorkerSession(
                worker_id="",
                worker_key=self.settings.worker_key,
                worker_token=worker_token,
                preferred_backend=self.settings.preferred_backend,
                allow_cpu_fallback=self.settings.allow_cpu_fallback,
                runtime_configuration=self.load_runtime_configuration(),
            )
        return self.register()

    def heartbeat(self) -> dict:
        session = self.ensure_registered()
        try:
            response = self.api_client.heartbeat(
                worker_token=session.worker_token,
                payload=self.build_heartbeat_payload(),
            )
        except WorkerAgentHttpError as error:
            session = self._reregister_after_auth_failure(error)
            response = self.api_client.heartbeat(
                worker_token=session.worker_token,
                payload=self.build_heartbeat_payload(),
            )
        runtime_configuration = self._resolve_runtime_configuration(
            response,
            fallback=session.runtime_configuration,
        )
        self.store_runtime_configuration(runtime_configuration)
        execution_preferences = self._resolve_execution_preferences(
            response,
            preferred_backend=session.preferred_backend,
            allow_cpu_fallback=session.allow_cpu_fallback,
        )
        session = WorkerSession(
            worker_id=str(response["worker_id"]),
            worker_key=str(response["worker_key"]),
            worker_token=session.worker_token,
            preferred_backend=execution_preferences["preferred_backend"],
            allow_cpu_fallback=execution_preferences["allow_cpu_fallback"],
            runtime_configuration=runtime_configuration,
        )
        return response

    def process_once(self) -> dict | None:
        session = self.ensure_registered()
        try:
            heartbeat = self.api_client.heartbeat(
                worker_token=session.worker_token,
                payload=self.build_heartbeat_payload(),
            )
        except WorkerAgentHttpError as error:
            session = self._reregister_after_auth_failure(error)
            heartbeat = self.api_client.heartbeat(
                worker_token=session.worker_token,
                payload=self.build_heartbeat_payload(),
            )
        runtime_configuration = self._resolve_runtime_configuration(
            heartbeat,
            fallback=session.runtime_configuration,
        )
        self.store_runtime_configuration(runtime_configuration)
        execution_preferences = self._resolve_execution_preferences(
            heartbeat,
            preferred_backend=session.preferred_backend,
            allow_cpu_fallback=session.allow_cpu_fallback,
        )
        session = WorkerSession(
            worker_id=str(heartbeat["worker_id"]),
            worker_key=str(heartbeat["worker_key"]),
            worker_token=session.worker_token,
            preferred_backend=execution_preferences["preferred_backend"],
            allow_cpu_fallback=execution_preferences["allow_cpu_fallback"],
            runtime_configuration=runtime_configuration,
        )
        try:
            assignment = self.api_client.request_job(worker_token=session.worker_token)
        except WorkerAgentHttpError as error:
            session = self._reregister_after_auth_failure(error)
            assignment = self.api_client.request_job(worker_token=session.worker_token)
        if assignment.get("status") != "assigned" or assignment.get("job") is None:
            logger.info(
                "remote worker job skipped",
                extra=_worker_log_extra(
                    "worker_job_skipped",
                    worker_key=session.worker_key,
                    reason=str(assignment.get("status") or "no_job"),
                ),
            )
            return None

        job = assignment["job"]
        job_id = str(job["job_id"])
        preview_backend = getattr(self.execution_service, "preview_backend", None)
        if callable(preview_backend) and job.get("job_kind") != "dry_run":
            backend_preview = preview_backend(
                job_id=job_id,
                plan_payload=dict(job["plan_payload"]),
                media_payload=dict(job["media_payload"]),
                scratch_dir_override=self._scratch_dir_for_runtime(session.runtime_configuration),
                preferred_backend=session.preferred_backend,
                allow_cpu_fallback=session.allow_cpu_fallback,
            )
        else:
            backend_preview = {
                "requested_backend": session.preferred_backend,
                "actual_backend": None,
                "actual_accelerator": None,
                "fallback_used": False,
                "selection_reason": None,
            }
        self.api_client.claim_job(worker_token=session.worker_token, job_id=job_id)
        logger.info(
            "remote worker job claimed",
            extra=_worker_log_extra(
                "worker_job_claimed",
                worker_key=session.worker_key,
                job_id=job_id,
                requested_backend=backend_preview.get("requested_backend"),
                selected_backend=backend_preview.get("actual_backend"),
                actual_accelerator=backend_preview.get("actual_accelerator"),
                backend_fallback_used=backend_preview.get("fallback_used"),
                backend_selection_reason=backend_preview.get("selection_reason"),
            ),
        )
        cancellation_state: dict[str, object] = {"requested": False, "reason": None}
        progress_reporter = self._build_progress_reporter(
            worker_token=session.worker_token,
            job_id=job_id,
            current_backend=(backend_preview.get("actual_backend") or backend_preview.get("requested_backend")),
            preferred_backend=session.preferred_backend,
            allow_cpu_fallback=session.allow_cpu_fallback,
            runtime_configuration=session.runtime_configuration,
            cancellation_state=cancellation_state,
        )
        execute_signature = inspect.signature(self.execution_service.execute)
        execute_parameters = execute_signature.parameters
        execute_kwargs = {
            "job_id": job_id,
            "plan_payload": dict(job["plan_payload"]),
            "media_payload": dict(job["media_payload"]),
        }
        if "job_kind" in execute_parameters:
            execute_kwargs["job_kind"] = str(job.get("job_kind") or "execution")
        if "analysis_request_payload" in execute_parameters:
            execute_kwargs["analysis_request_payload"] = (
                dict(job["analysis_payload"])
                if isinstance(job.get("analysis_payload"), dict)
                else None
            )
        if "progress_callback" in execute_parameters:
            execute_kwargs["progress_callback"] = progress_reporter
        if "scratch_dir_override" in execute_parameters:
            execute_kwargs["scratch_dir_override"] = self._scratch_dir_for_runtime(session.runtime_configuration)
        if "preferred_backend" in execute_parameters:
            execute_kwargs["preferred_backend"] = session.preferred_backend
        if "allow_cpu_fallback" in execute_parameters:
            execute_kwargs["allow_cpu_fallback"] = session.allow_cpu_fallback
        if "cancel_requested" in execute_parameters:
            execute_kwargs["cancel_requested"] = lambda: bool(cancellation_state.get("requested"))
        try:
            progress_reporter(
                ExecutionProgressUpdate(
                    stage="starting",
                    percent=0.0,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            logger.info(
                "remote worker job started",
                extra=_worker_log_extra(
                    "worker_job_started",
                    worker_key=session.worker_key,
                    job_id=job_id,
                    job_kind=str(job.get("job_kind") or "execution"),
                    requested_backend=backend_preview.get("requested_backend"),
                    selected_backend=backend_preview.get("actual_backend"),
                    actual_accelerator=backend_preview.get("actual_accelerator"),
                    backend_fallback_used=backend_preview.get("fallback_used"),
                ),
            )
            result = self.execution_service.execute(**execute_kwargs)
            response = self.api_client.submit_job_result(
                worker_token=session.worker_token,
                job_id=job_id,
                payload={
                    "result_payload": result.model_dump(mode="json"),
                    "runtime_summary": self._runtime_summary_for_job(
                        job_id=job_id,
                        current_backend=result.actual_backend or backend_preview.get("actual_backend") or backend_preview.get("requested_backend"),
                        current_stage=result.status,
                        current_progress_percent=100 if result.status == "completed" else None,
                        last_completed_job_id=job_id if result.status == "completed" else None,
                        preferred_backend=session.preferred_backend,
                        allow_cpu_fallback=session.allow_cpu_fallback,
                        runtime_configuration=session.runtime_configuration,
                    ),
                },
            )
            log_extra = _worker_log_extra(
                "worker_job_failed" if result.status == "failed" else "worker_job_finished",
                worker_key=session.worker_key,
                job_id=job_id,
                final_status=response.get("final_status") or result.status,
                failure_message=result.failure_message,
                failure_category=result.failure_category,
                requested_backend=result.requested_backend,
                actual_backend=result.actual_backend,
                actual_accelerator=result.actual_accelerator,
                backend_fallback_used=result.backend_fallback_used,
            )
            if result.status == "failed":
                logger.error("remote worker job failed", extra=log_extra)
            else:
                logger.info("remote worker job finished", extra=log_extra)
            return response
        except Exception as error:
            logger.error(
                "remote worker job failed unexpectedly",
                extra=_worker_log_extra(
                    "worker_job_failed",
                    worker_key=session.worker_key,
                    job_id=job_id,
                    failure_category="worker_agent_error",
                    reason=str(error),
                    exception_type=type(error).__name__,
                    current_backend=backend_preview.get("actual_backend") or backend_preview.get("requested_backend"),
                ),
            )
            self._best_effort_report_failure(
                session=session,
                job_id=job_id,
                failure_message=str(error),
                failure_category="worker_agent_error",
                current_backend=(backend_preview.get("actual_backend") or backend_preview.get("requested_backend")),
            )
            raise

    def _best_effort_report_failure(
        self,
        *,
        session: WorkerSession,
        job_id: str,
        failure_message: str,
        failure_category: str,
        current_backend: str | None,
    ) -> None:
        try:
            self.api_client.report_job_failure(
                worker_token=session.worker_token,
                job_id=job_id,
                payload={
                    "failure_message": failure_message,
                    "failure_category": failure_category,
                    "runtime_summary": self._runtime_summary_for_job(
                        job_id=job_id,
                        current_backend=current_backend,
                        current_stage="failed",
                        preferred_backend=session.preferred_backend,
                        allow_cpu_fallback=session.allow_cpu_fallback,
                        runtime_configuration=session.runtime_configuration,
                    ),
                },
            )
        except Exception:
            return

    def _reregister_after_auth_failure(self, error: WorkerAgentHttpError) -> WorkerSession:
        if error.status_code != 401:
            raise error
        if not self.settings.pairing_token or not self._pairing_token_available:
            raise error
        self.clear_stored_worker_token()
        return self.register()

    def _resolve_execution_preferences(
        self,
        payload: dict,
        *,
        preferred_backend: str | None = None,
        allow_cpu_fallback: bool | None = None,
    ) -> dict[str, object]:
        response_preferences = payload.get("execution_preferences")
        if isinstance(response_preferences, dict):
            return {
                "preferred_backend": coerce_backend_preference(
                    response_preferences.get("preferred_backend")
                    or preferred_backend
                    or self.settings.preferred_backend
                ),
                "allow_cpu_fallback": bool(
                    response_preferences.get("allow_cpu_fallback")
                    if response_preferences.get("allow_cpu_fallback") is not None
                    else allow_cpu_fallback
                    if allow_cpu_fallback is not None
                    else self.settings.allow_cpu_fallback
                ),
            }
        return {
            "preferred_backend": coerce_backend_preference(preferred_backend or self.settings.preferred_backend),
            "allow_cpu_fallback": self.settings.allow_cpu_fallback if allow_cpu_fallback is None else allow_cpu_fallback,
        }

    def _build_progress_reporter(
        self,
        *,
        worker_token: str,
        job_id: str,
        current_backend: str | None,
        preferred_backend: str,
        allow_cpu_fallback: bool,
        runtime_configuration: dict[str, object],
        cancellation_state: dict[str, object],
    ):
        last_sent_at: datetime | None = None
        last_percent: int | None = None
        last_logged_stage: str | None = None

        def report(update) -> None:
            nonlocal last_sent_at, last_percent, last_logged_stage
            now = datetime.now(timezone.utc)
            current_percent = int(update.percent) if update.percent is not None else None
            if update.stage != last_logged_stage:
                logger.info(
                    "remote worker job progress stage changed",
                    extra=_worker_log_extra(
                        "worker_job_progress",
                        job_id=job_id,
                        current_backend=current_backend,
                        stage=update.stage,
                        percent=update.percent,
                        out_time_seconds=update.out_time_seconds,
                        fps=update.fps,
                        speed=update.speed,
                    ),
                )
                last_logged_stage = update.stage
            should_send = (
                last_sent_at is None
                or update.stage != "encoding"
                or current_percent is None
                or last_percent is None
                or current_percent >= last_percent + 2
                or (now - last_sent_at).total_seconds() >= 2
            )
            if not should_send:
                return
            response = self.api_client.report_job_progress(
                worker_token=worker_token,
                job_id=job_id,
                payload={
                    "stage": update.stage,
                    "percent": update.percent,
                    "out_time_seconds": update.out_time_seconds,
                    "fps": update.fps,
                    "speed": update.speed,
                    "runtime_summary": self._runtime_summary_for_job(
                        job_id=job_id,
                        current_backend=current_backend,
                        current_stage=update.stage,
                        current_progress_percent=int(update.percent) if update.percent is not None else None,
                        preferred_backend=preferred_backend,
                        allow_cpu_fallback=allow_cpu_fallback,
                        runtime_configuration=runtime_configuration,
                    ),
                },
            )
            if response.get("cancellation_requested"):
                cancellation_state["requested"] = True
                cancellation_state["reason"] = response.get("cancellation_reason")
            last_sent_at = now
            last_percent = current_percent

        return report

    def _runtime_summary_for_job(
        self,
        *,
        job_id: str | None = None,
        current_backend: str | None = None,
        current_stage: str | None = None,
        current_progress_percent: int | None = None,
        last_completed_job_id: str | None = None,
        preferred_backend: str | None = None,
        allow_cpu_fallback: bool | None = None,
        runtime_configuration: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        base_runtime = build_runtime_summary(
            self.settings,
            runtime_configuration=runtime_configuration or self.load_runtime_configuration(),
            include_backend_diagnostics=False,
        )
        return clean_runtime_summary_payload(base_runtime | {
            "preferred_backend": coerce_backend_preference(
                preferred_backend or str(base_runtime.get("preferred_backend") or self.settings.preferred_backend)
            ),
            "allow_cpu_fallback": self.settings.allow_cpu_fallback if allow_cpu_fallback is None else allow_cpu_fallback,
            "current_job_id": job_id,
            "current_backend": current_backend,
            "current_stage": current_stage,
            "current_progress_percent": current_progress_percent,
            "current_progress_updated_at": now.isoformat() if job_id is not None else None,
            "last_completed_job_id": last_completed_job_id,
            "telemetry": collect_runtime_telemetry(current_backend=current_backend),
        })

    @staticmethod
    def _scratch_dir_for_runtime(runtime_configuration: dict[str, object]) -> str | None:
        value = runtime_configuration.get("scratch_dir")
        return None if value is None else str(value)

    @staticmethod
    def _resolve_runtime_configuration(
        payload: dict,
        *,
        fallback: dict[str, object] | None = None,
    ) -> dict[str, object]:
        runtime_configuration = payload.get("runtime_configuration")
        if isinstance(runtime_configuration, dict):
            return runtime_configuration
        return dict(fallback or {})
