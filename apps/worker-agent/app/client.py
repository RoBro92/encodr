from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib import error, request


class HttpRequester(Protocol):
    def request_json(
        self,
        *,
        method: str,
        url: str,
        body: dict | None = None,
        bearer_token: str | None = None,
    ) -> dict:
        ...


class UrllibRequester:
    def request_json(
        self,
        *,
        method: str,
        url: str,
        body: dict | None = None,
        bearer_token: str | None = None,
    ) -> dict:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        req = request.Request(url, data=payload, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=10) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            raise WorkerAgentHttpError(exc.code, response_body) from exc
        except error.URLError as exc:
            raise WorkerAgentHttpError(0, str(exc.reason)) from exc
        return json.loads(response_body or "{}")


@dataclass(frozen=True, slots=True)
class WorkerAgentHttpError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


class WorkerApiClient:
    def __init__(self, *, base_url: str, requester: HttpRequester | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.requester = requester or UrllibRequester()

    def register(self, payload: dict) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/register",
            body=payload,
        )

    def heartbeat(self, *, worker_token: str, payload: dict) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/heartbeat",
            body=payload,
            bearer_token=worker_token,
        )

    def request_job(self, *, worker_token: str) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/jobs/request",
            bearer_token=worker_token,
        )

    def claim_job(self, *, worker_token: str, job_id: str) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/jobs/{job_id}/claim",
            bearer_token=worker_token,
        )

    def submit_job_result(self, *, worker_token: str, job_id: str, payload: dict) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/jobs/{job_id}/result",
            body=payload,
            bearer_token=worker_token,
        )

    def report_job_failure(self, *, worker_token: str, job_id: str, payload: dict) -> dict:
        return self.requester.request_json(
            method="POST",
            url=f"{self.base_url}/worker/jobs/{job_id}/failure",
            body=payload,
            bearer_token=worker_token,
        )
