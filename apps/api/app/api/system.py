from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.system import PathStatusResponse, RuntimeStatusResponse, StorageStatusResponse
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
    return StorageStatusResponse(
        scratch=PathStatusResponse(**system.path_status(config_bundle.app.scratch_dir)),
        data_dir=PathStatusResponse(**system.path_status(config_bundle.app.data_dir)),
        media_mounts=[
            PathStatusResponse(**system.path_status(path))
            for path in config_bundle.workers.local.media_mounts
        ],
    )


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
    return RuntimeStatusResponse(
        version=system.app_version,
        environment=config_bundle.app.environment.value,
        db_reachable=system.db_reachable(),
        auth_enabled=config_bundle.app.auth.enabled,
        api_base_path=config_bundle.app.api.base_path,
        scratch_dir=config_bundle.app.scratch_dir.as_posix(),
        data_dir=config_bundle.app.data_dir.as_posix(),
        media_mounts=[path.as_posix() for path in config_bundle.workers.local.media_mounts],
    )
