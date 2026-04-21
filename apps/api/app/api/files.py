from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_config_bundle, get_session, require_admin_user
from app.schemas.files import (
    BatchPlanItemResponse,
    BatchPlanResponse,
    FileListResponse,
    FilePathRequest,
    FileSelectionRequest,
    FolderBrowseResponse,
    FolderScanSummaryResponse,
    PlanFileResponse,
    ProbeFileResponse,
    DryRunBatchResponse,
    DryRunItemResponse,
    TrackedFileDetailResponse,
    TrackedFileSummaryResponse,
)
from app.schemas.plans import PlanSnapshotDetailResponse, ProbeSnapshotDetailResponse
from app.services.errors import ApiServiceError
from app.services.files import FilesService
from app.services.library import LibraryService
from app.services.plans import PlansService
from app.services.review import ReviewService
from encodr_core.config import ConfigBundle
from encodr_db.models import ComplianceState, FileLifecycleState, User
from encodr_db.repositories import TrackedFileRepository

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(require_admin_user)],
)


def get_files_service(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> FilesService:
    return FilesService(
        config_bundle=config_bundle,
        probe_client_factory=request.app.state.probe_client_factory,
    )


def get_plans_service(
    files_service: FilesService = Depends(get_files_service),
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> PlansService:
    return PlansService(config_bundle=config_bundle, files_service=files_service)


def get_library_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> LibraryService:
    return LibraryService(config_bundle=config_bundle)


def get_review_service(
    files_service: FilesService = Depends(get_files_service),
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> ReviewService:
    return ReviewService(plans_service=PlansService(config_bundle=config_bundle, files_service=files_service))


def _raise_service_error(error: ApiServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("", response_model=FileListResponse)
def list_files(
    lifecycle_state: FileLifecycleState | None = None,
    compliance_state: ComplianceState | None = None,
    protected_only: bool | None = None,
    path_prefix: str | None = None,
    path_search: str | None = None,
    is_4k: bool | None = None,
    limit: int | None = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    files_service: FilesService = Depends(get_files_service),
    current_user: User = Depends(require_admin_user),
) -> FileListResponse:
    del current_user
    tracked_files = files_service.list_files(
        session,
        lifecycle_state=lifecycle_state,
        compliance_state=compliance_state,
        protected_only=protected_only,
        path_prefix=path_prefix,
        path_search=path_search,
        is_4k=is_4k,
        limit=limit,
        offset=offset,
    )
    return FileListResponse(
        items=[TrackedFileSummaryResponse.from_model(item) for item in tracked_files],
        limit=limit,
        offset=offset,
    )


@router.get("/browse", response_model=FolderBrowseResponse)
def browse_folder(
    path: str | None = None,
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> FolderBrowseResponse:
    del current_user
    try:
        return FolderBrowseResponse(**library_service.browse_directory(path))
    except ApiServiceError as error:
        _raise_service_error(error)


@router.post("/scan", response_model=FolderScanSummaryResponse)
def scan_folder(
    payload: FilePathRequest,
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> FolderScanSummaryResponse:
    del current_user
    try:
        return FolderScanSummaryResponse(**library_service.scan_directory(payload.source_path))
    except ApiServiceError as error:
        _raise_service_error(error)


@router.post("/dry-run", response_model=DryRunBatchResponse)
def dry_run(
    payload: FileSelectionRequest,
    plans_service: PlansService = Depends(get_plans_service),
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> DryRunBatchResponse:
    del current_user
    try:
        scope, source_files = library_service.resolve_selection(
            source_path=payload.source_path,
            folder_path=payload.folder_path,
            selected_paths=payload.selected_paths,
        )
        items: list[DryRunItemResponse] = []
        for source_file in source_files:
            _media_file, plan = plans_service.dry_run_file(source_path=source_file.as_posix())
            items.append(
                DryRunItemResponse(
                    source_path=source_file.as_posix(),
                    file_name=source_file.name,
                    action=plan.action.value,
                    confidence=plan.confidence.value,
                    requires_review=plan.action.value == "manual_review" or plan.should_treat_as_protected,
                    is_protected=plan.should_treat_as_protected,
                    reason_codes=[reason.code for reason in plan.reasons],
                    warning_codes=[warning.code for warning in plan.warnings],
                    selected_audio_stream_indices=plan.selected_streams.audio_stream_indices,
                    selected_subtitle_stream_indices=plan.selected_streams.subtitle_stream_indices,
                )
            )
        return DryRunBatchResponse(
            scope=scope,
            total_files=len(items),
            protected_count=sum(1 for item in items if item.is_protected),
            review_count=sum(1 for item in items if item.requires_review),
            actions=library_service.summarise_actions([item.action for item in items]),
            items=items,
        )
    except ApiServiceError as error:
        _raise_service_error(error)


@router.post("/batch-plan", response_model=BatchPlanResponse)
def batch_plan(
    payload: FileSelectionRequest,
    session: Session = Depends(get_session),
    plans_service: PlansService = Depends(get_plans_service),
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> BatchPlanResponse:
    del current_user
    try:
        scope, source_files = library_service.resolve_selection(
            source_path=payload.source_path,
            folder_path=payload.folder_path,
            selected_paths=payload.selected_paths,
        )
        items: list[BatchPlanItemResponse] = []
        for source_file in source_files:
            tracked_file, probe_snapshot, plan_snapshot = plans_service.plan_file(
                session,
                source_path=source_file.as_posix(),
            )
            items.append(
                BatchPlanItemResponse(
                    tracked_file=TrackedFileSummaryResponse.from_model(tracked_file),
                    latest_probe_snapshot=ProbeSnapshotDetailResponse.from_snapshot(probe_snapshot),
                    latest_plan_snapshot=PlanSnapshotDetailResponse.from_snapshot(plan_snapshot),
                )
            )
        session.commit()
        return BatchPlanResponse(
            scope=scope,
            total_files=len(items),
            actions=library_service.summarise_actions([item.latest_plan_snapshot.action for item in items]),
            items=items,
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.get("/{file_id}", response_model=TrackedFileDetailResponse)
def get_file_detail(
    file_id: str,
    session: Session = Depends(get_session),
    files_service: FilesService = Depends(get_files_service),
    review_service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> TrackedFileDetailResponse:
    del current_user
    try:
        tracked_file = files_service.get_file(session, file_id=file_id)
    except ApiServiceError as error:
        _raise_service_error(error)
    repository = TrackedFileRepository(session)
    latest_probe = repository.get_latest_probe_snapshot(tracked_file.id)
    latest_plan = repository.get_latest_plan_snapshot(tracked_file.id)
    summary = TrackedFileSummaryResponse.from_model(tracked_file).model_dump()
    try:
        review_item = review_service.get_item(session, item_id=tracked_file.id)
        summary["requires_review"] = review_item.requires_review
        summary["review_status"] = review_item.review_status
        summary["protected_source"] = review_item.protected_state.source
        summary["operator_protected"] = review_item.protected_state.operator_protected
        summary["operator_protected_note"] = review_item.protected_state.note
    except ApiServiceError:
        pass
    return TrackedFileDetailResponse(
        **summary,
        latest_probe_snapshot_id=latest_probe.id if latest_probe is not None else None,
        latest_plan_snapshot_id=latest_plan.id if latest_plan is not None else None,
    )


@router.get("/{file_id}/probe-snapshots/latest", response_model=ProbeSnapshotDetailResponse)
def get_latest_probe_snapshot(
    file_id: str,
    session: Session = Depends(get_session),
    files_service: FilesService = Depends(get_files_service),
    current_user: User = Depends(require_admin_user),
) -> ProbeSnapshotDetailResponse:
    del current_user
    try:
        snapshot = files_service.get_latest_probe_snapshot(session, file_id=file_id)
        return ProbeSnapshotDetailResponse.from_snapshot(snapshot)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.get("/{file_id}/plan-snapshots/latest", response_model=PlanSnapshotDetailResponse)
def get_latest_plan_snapshot(
    file_id: str,
    session: Session = Depends(get_session),
    files_service: FilesService = Depends(get_files_service),
    current_user: User = Depends(require_admin_user),
) -> PlanSnapshotDetailResponse:
    del current_user
    try:
        snapshot = files_service.get_latest_plan_snapshot(session, file_id=file_id)
        return PlanSnapshotDetailResponse.from_snapshot(snapshot)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.post("/probe", response_model=ProbeFileResponse)
def probe_file(
    payload: FilePathRequest,
    session: Session = Depends(get_session),
    files_service: FilesService = Depends(get_files_service),
    current_user: User = Depends(require_admin_user),
) -> ProbeFileResponse:
    del current_user
    try:
        tracked_file, probe_snapshot = files_service.probe_file(session, source_path=payload.source_path)
        session.commit()
        return ProbeFileResponse(
            tracked_file=TrackedFileSummaryResponse.from_model(tracked_file),
            latest_probe_snapshot=ProbeSnapshotDetailResponse.from_snapshot(probe_snapshot),
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/plan", response_model=PlanFileResponse)
def plan_file(
    payload: FilePathRequest,
    session: Session = Depends(get_session),
    plans_service: PlansService = Depends(get_plans_service),
    current_user: User = Depends(require_admin_user),
) -> PlanFileResponse:
    del current_user
    try:
        tracked_file, probe_snapshot, plan_snapshot = plans_service.plan_file(
            session,
            source_path=payload.source_path,
        )
        session.commit()
        return PlanFileResponse(
            tracked_file=TrackedFileSummaryResponse.from_model(tracked_file),
            latest_probe_snapshot=ProbeSnapshotDetailResponse.from_snapshot(probe_snapshot),
            latest_plan_snapshot=PlanSnapshotDetailResponse.from_snapshot(plan_snapshot),
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)

