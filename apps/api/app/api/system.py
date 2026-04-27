from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.jobs import JobSummaryResponse
from app.schemas.system import (
    DiagnosticLogEventResponse,
    DiagnosticLogsResponse,
    PathStatusResponse,
    RuntimeStatusResponse,
    StorageStatusResponse,
    UpdateStatusResponse,
)
from app.schemas.worker import QueueHealthSummaryResponse
from app.services.system import SystemService
from encodr_core.config import ConfigBundle
from encodr_db.models import User
from encodr_db.repositories import JobRepository, WorkerRepository
from encodr_shared import build_diagnostic_bundle, read_log_events

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_admin_user)],
)


@router.get("/storage", response_model=StorageStatusResponse)
def get_storage_status(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> StorageStatusResponse:
    del current_user
    system = SystemService(
        config_bundle=config_bundle,
        session_factory=None,
        app_version=request.app.state.app_version,
    )
    payload = system.storage_status()
    payload["scratch"] = PathStatusResponse(**payload["scratch"])
    payload["data_dir"] = PathStatusResponse(**payload["data_dir"])
    payload["media_mounts"] = [
        PathStatusResponse(**item)
        for item in payload["media_mounts"]
    ]
    return StorageStatusResponse(**payload)


@router.get("/runtime", response_model=RuntimeStatusResponse)
def get_runtime_status(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> RuntimeStatusResponse:
    del current_user
    system = SystemService(
        config_bundle=config_bundle,
        session_factory=session_factory,
        app_version=request.app.state.app_version,
    )
    payload = system.runtime_status()
    payload["queue_health"] = QueueHealthSummaryResponse(**payload["queue_health"])
    return RuntimeStatusResponse(**payload)


@router.get("/update", response_model=UpdateStatusResponse)
def get_update_status(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> UpdateStatusResponse:
    del current_user
    system = SystemService(
        config_bundle=config_bundle,
        session_factory=session_factory,
        app_version=request.app.state.app_version,
    )
    payload = system.update_status(request.app.state.update_checker)
    return UpdateStatusResponse(**payload)


@router.post("/update/check", response_model=UpdateStatusResponse)
def check_update_status(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> UpdateStatusResponse:
    del current_user
    system = SystemService(
        config_bundle=config_bundle,
        session_factory=session_factory,
        app_version=request.app.state.app_version,
    )
    payload = system.update_status(request.app.state.update_checker, refresh=True)
    return UpdateStatusResponse(**payload)


@router.get("/logs", response_model=DiagnosticLogsResponse)
def get_diagnostic_logs(
    component: str | None = None,
    level: str | None = None,
    limit: int = 100,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> DiagnosticLogsResponse:
    del current_user
    log_dir = config_bundle.app.data_dir / "logs"
    items = read_log_events(
        log_dir,
        component=component or None,
        level=level or None,
        limit=max(1, min(limit, 500)),
    )
    return DiagnosticLogsResponse(
        retention_days=config_bundle.app.diagnostics.retention_days,
        log_dir=log_dir.as_posix(),
        items=[DiagnosticLogEventResponse(**asdict(item)) for item in items],
    )


@router.get("/diagnostics/bundle")
def download_diagnostic_bundle(
    request: Request,
    time_range: str = "last_day",
    redact_paths: bool = False,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> Response:
    del current_user
    system = SystemService(
        config_bundle=config_bundle,
        session_factory=session_factory,
        app_version=request.app.state.app_version,
    )
    runtime = system.runtime_status()
    storage = system.storage_status()
    runtime["queue_health"] = dict(runtime["queue_health"])
    since = _diagnostic_since(time_range)
    with session_factory() as session:
        workers = [
            {
                "id": worker.id,
                "worker_key": worker.worker_key,
                "display_name": worker.display_name,
                "worker_type": worker.worker_type.value,
                "enabled": worker.enabled,
                "registration_status": worker.registration_status.value,
                "health_status": worker.last_health_status.value,
                "health_summary": worker.last_health_summary,
                "last_seen_at": worker.last_seen_at.isoformat() if worker.last_seen_at else None,
                "last_heartbeat_at": worker.last_heartbeat_at.isoformat() if worker.last_heartbeat_at else None,
                "preferred_backend": worker.preferred_backend,
                "runtime_summary": worker.runtime_payload,
                "capability_summary": worker.capability_payload,
            }
            for worker in WorkerRepository(session).list_workers(limit=100)
        ]
        jobs = [
            JobSummaryResponse.from_model(job).model_dump(mode="json")
            for job in JobRepository(session).list_jobs(limit=100, include_cleared=True)
        ]
    bundle = build_diagnostic_bundle(
        log_dir=config_bundle.app.data_dir / "logs",
        summary={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "time_range": time_range,
            "redact_paths": redact_paths,
            "version": request.app.state.app_version,
        },
        health={"runtime": runtime, "storage": storage},
        workers={"items": workers},
        jobs_recent={"items": jobs},
        config_summary=system.effective_config().model_dump(mode="json"),
        since=since,
        redact_paths=redact_paths,
    )
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="encodr-diagnostics.zip"'},
    )


def _diagnostic_since(time_range: str) -> datetime:
    now = datetime.now(timezone.utc)
    return {
        "last_hour": now - timedelta(hours=1),
        "last_6_hours": now - timedelta(hours=6),
        "last_day": now - timedelta(days=1),
        "last_week": now - timedelta(days=7),
    }.get(time_range, now - timedelta(days=1))
