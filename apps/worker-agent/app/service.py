from __future__ import annotations

import inspect
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
)
from app.client import WorkerApiClient
from app.config import WorkerAgentSettings
from app.execution import RemoteExecutionService


@dataclass(frozen=True, slots=True)
class WorkerSession:
    worker_id: str
    worker_key: str
    worker_token: str


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

    def build_registration_payload(self) -> dict:
        health_status, health_summary = build_worker_health(self.settings)
        return {
            "registration_secret": self.settings.registration_secret,
            "worker_key": self.settings.worker_key,
            "display_name": self.settings.display_name,
            "worker_type": "remote",
            "capability_summary": build_capability_summary(self.settings),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(self.settings),
            "binary_summary": build_binary_summary(self.settings),
            "health_status": health_status,
            "health_summary": health_summary,
        }

    def build_heartbeat_payload(self) -> dict:
        health_status, health_summary = build_worker_health(self.settings)
        return {
            "capability_summary": build_capability_summary(self.settings),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(self.settings),
            "binary_summary": build_binary_summary(self.settings),
            "health_status": health_status,
            "health_summary": health_summary,
        }

    def register(self) -> WorkerSession:
        if not self.settings.registration_secret:
            raise RuntimeError("A registration secret is required when no worker token is configured.")
        response = self.api_client.register(self.build_registration_payload())
        worker_token = str(response["worker_token"])
        self.store_worker_token(worker_token)
        return WorkerSession(
            worker_id=str(response["worker_id"]),
            worker_key=str(response["worker_key"]),
            worker_token=worker_token,
        )

    def ensure_registered(self) -> WorkerSession:
        worker_token = self.load_worker_token()
        if worker_token:
            return WorkerSession(worker_id="", worker_key=self.settings.worker_key, worker_token=worker_token)
        return self.register()

    def heartbeat(self) -> dict:
        session = self.ensure_registered()
        return self.api_client.heartbeat(
            worker_token=session.worker_token,
            payload=self.build_heartbeat_payload(),
        )

    def process_once(self) -> dict | None:
        session = self.ensure_registered()
        self.api_client.heartbeat(
            worker_token=session.worker_token,
            payload=self.build_heartbeat_payload(),
        )
        assignment = self.api_client.request_job(worker_token=session.worker_token)
        if assignment.get("status") != "assigned" or assignment.get("job") is None:
            return None

        job = assignment["job"]
        self.api_client.claim_job(worker_token=session.worker_token, job_id=str(job["job_id"]))
        progress_reporter = self._build_progress_reporter(
            worker_token=session.worker_token,
            job_id=str(job["job_id"]),
        )
        execute_kwargs = {
            "job_id": str(job["job_id"]),
            "plan_payload": dict(job["plan_payload"]),
            "media_payload": dict(job["media_payload"]),
        }
        if "progress_callback" in inspect.signature(self.execution_service.execute).parameters:
            execute_kwargs["progress_callback"] = progress_reporter
        result = self.execution_service.execute(**execute_kwargs)
        response = self.api_client.submit_job_result(
            worker_token=session.worker_token,
            job_id=str(job["job_id"]),
            payload={
                "result_payload": result.model_dump(mode="json"),
                "runtime_summary": build_runtime_summary(self.settings) | {"last_completed_job_id": str(job["job_id"])},
            },
        )
        return response

    def _build_progress_reporter(self, *, worker_token: str, job_id: str):
        last_sent_at: datetime | None = None
        last_percent: int | None = None

        def report(update) -> None:
            nonlocal last_sent_at, last_percent
            now = datetime.now(timezone.utc)
            current_percent = int(update.percent) if update.percent is not None else None
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
            self.api_client.report_job_progress(
                worker_token=worker_token,
                job_id=job_id,
                payload={
                    "stage": update.stage,
                    "percent": update.percent,
                    "out_time_seconds": update.out_time_seconds,
                    "fps": update.fps,
                    "speed": update.speed,
                    "runtime_summary": build_runtime_summary(self.settings),
                },
            )
            last_sent_at = now
            last_percent = current_percent

        return report
