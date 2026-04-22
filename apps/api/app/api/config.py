from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, model_validator

from app.core.dependencies import get_config_bundle, get_session_factory, require_admin_user
from app.schemas.config import (
    EffectiveConfigResponse,
    ExecutionPreferencesResponse,
    LibraryRootsResponse,
    ProcessingRulesResponse,
)
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


class UpdateProcessingRulesetRequest(BaseModel):
    target_video_codec: str
    output_container: str
    preferred_audio_languages: list[str] | None = None
    keep_only_preferred_audio_languages: bool | None = None
    preserve_surround: bool
    preserve_seven_one: bool | None = None
    preserve_atmos: bool
    preferred_subtitle_languages: list[str] | None = None
    keep_forced_subtitles: bool
    keep_one_full_preferred_subtitle: bool | None = None
    drop_other_subtitles: bool | None = None
    handling_mode: str | None = None
    target_quality_mode: str | None = None
    max_allowed_video_reduction_percent: int | None = None
    keep_english_audio_only: bool | None = None
    keep_one_full_english_subtitle: bool | None = None
    four_k_mode: str | None = None

    @model_validator(mode="after")
    def apply_legacy_defaults(self) -> "UpdateProcessingRulesetRequest":
        if self.preferred_audio_languages is None:
            self.preferred_audio_languages = ["eng"]
        if self.keep_only_preferred_audio_languages is None:
            self.keep_only_preferred_audio_languages = (
                self.keep_english_audio_only if self.keep_english_audio_only is not None else True
            )
        if self.preserve_seven_one is None:
            self.preserve_seven_one = True
        if self.preferred_subtitle_languages is None:
            self.preferred_subtitle_languages = ["eng"]
        if self.keep_one_full_preferred_subtitle is None:
            self.keep_one_full_preferred_subtitle = (
                self.keep_one_full_english_subtitle if self.keep_one_full_english_subtitle is not None else True
            )
        if self.drop_other_subtitles is None:
            self.drop_other_subtitles = True
        if self.handling_mode is None:
            self.handling_mode = "strip_only" if self.four_k_mode == "strip_only" else "transcode"
        if self.target_quality_mode is None:
            self.target_quality_mode = "high_quality"
        if self.max_allowed_video_reduction_percent is None:
            self.max_allowed_video_reduction_percent = 35
        return self


class UpdateProcessingRulesRequest(BaseModel):
    movies: UpdateProcessingRulesetRequest | None = None
    movies_4k: UpdateProcessingRulesetRequest | None = None
    tv: UpdateProcessingRulesetRequest | None = None
    tv_4k: UpdateProcessingRulesetRequest | None = None


class UpdateExecutionPreferencesRequest(BaseModel):
    preferred_backend: str
    allow_cpu_fallback: bool = True


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


@router.get("/setup/processing-rules", response_model=ProcessingRulesResponse)
def get_processing_rules(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> ProcessingRulesResponse:
    del current_user
    try:
        payload = SetupStateService(config_bundle=config_bundle).get_processing_rules()
        return ProcessingRulesResponse(**payload)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.put("/setup/processing-rules", response_model=ProcessingRulesResponse)
def update_processing_rules(
    payload: UpdateProcessingRulesRequest,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> ProcessingRulesResponse:
    del current_user
    try:
        state = SetupStateService(config_bundle=config_bundle).update_processing_rules(
            movies=payload.movies.model_dump(mode="json") if payload.movies is not None else None,
            movies_4k=payload.movies_4k.model_dump(mode="json") if payload.movies_4k is not None else None,
            tv=payload.tv.model_dump(mode="json") if payload.tv is not None else None,
            tv_4k=payload.tv_4k.model_dump(mode="json") if payload.tv_4k is not None else None,
        )
        return ProcessingRulesResponse(**state)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.get("/setup/execution-preferences", response_model=ExecutionPreferencesResponse)
def get_execution_preferences(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> ExecutionPreferencesResponse:
    del current_user
    try:
        payload = SetupStateService(config_bundle=config_bundle).get_execution_preferences()
        return ExecutionPreferencesResponse(**payload)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.put("/setup/execution-preferences", response_model=ExecutionPreferencesResponse)
def update_execution_preferences(
    payload: UpdateExecutionPreferencesRequest,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
) -> ExecutionPreferencesResponse:
    del current_user
    try:
        state = SetupStateService(config_bundle=config_bundle).update_execution_preferences(
            preferred_backend=payload.preferred_backend,  # type: ignore[arg-type]
            allow_cpu_fallback=payload.allow_cpu_fallback,
        )
        return ExecutionPreferencesResponse(**state)
    except ApiServiceError as error:
        _raise_service_error(error)
