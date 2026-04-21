from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.config import EffectiveConfigResponse, LibraryRootsResponse
from app.services.errors import ApiServiceError
from app.services.library import LibraryService
from app.services.setup import SetupStateService
from app.services.system import SystemService
from encodr_core.config import ConfigBundle
from encodr_db.models import User

router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_admin_user)],
)


def _raise_service_error(error: ApiServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


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


class UpdateLibraryRootsRequest(BaseModel):
    movies_root: str | None = None
    tv_root: str | None = None


@router.get("/setup/library-roots", response_model=LibraryRootsResponse)
def get_library_roots(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> LibraryRootsResponse:
    del current_user
    try:
        state = SetupStateService(config_bundle=config_bundle).get_state()
        media_root = LibraryService(config_bundle=config_bundle).default_root().as_posix()
        return LibraryRootsResponse(
            media_root=media_root,
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
        )
    except ApiServiceError as error:
        _raise_service_error(error)


@router.put("/setup/library-roots", response_model=LibraryRootsResponse)
def update_library_roots(
    payload: UpdateLibraryRootsRequest,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> LibraryRootsResponse:
    del current_user
    try:
        library_service = LibraryService(config_bundle=config_bundle)
        state = SetupStateService(config_bundle=config_bundle).update_state(
            movies_root=payload.movies_root,
            tv_root=payload.tv_root,
            allowed_roots=library_service.allowed_roots(),
        )
        return LibraryRootsResponse(
            media_root=library_service.default_root().as_posix(),
            movies_root=state["movies_root"],
            tv_root=state["tv_root"],
        )
    except ApiServiceError as error:
        _raise_service_error(error)
