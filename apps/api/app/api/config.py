from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.config import EffectiveConfigResponse
from app.services.system import SystemService
from encodr_core.config import ConfigBundle
from encodr_db.models import User

router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_admin_user)],
)


@router.get("/effective", response_model=EffectiveConfigResponse)
def get_effective_config(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> EffectiveConfigResponse:
    del current_user
    return SystemService(
        config_bundle=config_bundle,
        session_factory=session_factory,
        app_version=request.app.state.app_version,
    ).effective_config()
