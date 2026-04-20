from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from app.capabilities import (
    build_binary_summary,
    build_capability_summary,
    build_host_summary,
    build_runtime_summary,
)
from app.client import WorkerApiClient
from app.config import WorkerAgentSettings


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
    ) -> None:
        self.settings = settings
        self.api_client = api_client

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
        return {
            "registration_secret": self.settings.registration_secret,
            "worker_key": self.settings.worker_key,
            "display_name": self.settings.display_name,
            "worker_type": "remote",
            "capability_summary": build_capability_summary(self.settings),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(self.settings),
            "binary_summary": build_binary_summary(),
            "health_status": "healthy",
            "health_summary": "Remote worker registered and ready for future dispatch capabilities.",
        }

    def build_heartbeat_payload(self) -> dict:
        return {
            "capability_summary": build_capability_summary(self.settings),
            "host_summary": build_host_summary(),
            "runtime_summary": build_runtime_summary(self.settings),
            "binary_summary": build_binary_summary(),
            "health_status": "healthy",
            "health_summary": "Remote worker heartbeat succeeded.",
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
