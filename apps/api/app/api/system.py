from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.system import PathStatusResponse, RuntimeStatusResponse, StorageStatusResponse, UpdateStatusResponse
from app.schemas.worker import QueueHealthSummaryResponse
from app.services.system import SystemService
from encodr_core.config import ConfigBundle
from encodr_db.models import User

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
