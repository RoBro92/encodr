from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_config_bundle, get_local_worker_loop, get_session, get_session_factory, require_admin_user
from app.schemas.jobs import (
    BatchJobCreateResponse,
    BatchJobItemResponse,
    BulkJobActionResponse,
    CreateBatchJobsRequest,
    CreateDryRunJobsRequest,
    CreateJobRequest,
    DryRunJobCreateResponse,
    JobDetailResponse,
    JobBackupListResponse,
    JobBackupResponse,
    JobListResponse,
    JobSummaryResponse,
)
from app.services.errors import ApiServiceError
from app.services.files import FilesService
from app.services.library import LibraryService
from app.services.jobs import JobsService
from app.services.plans import PlansService
from app.services.review import ReviewService
from encodr_core.config import ConfigBundle
from encodr_core.media.models import MediaFile
from encodr_db.models import JobKind, JobStatus, User
from encodr_db.repositories import WorkerRepository
from encodr_db.runtime import LocalWorkerLoop
from encodr_shared.scheduling import schedule_windows_allow_now, schedule_windows_summary

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_admin_user)],
)

ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _raise_service_error(error: ApiServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


def get_review_service(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> ReviewService:
    files_service = FilesService(
        config_bundle=config_bundle,
        probe_client_factory=request.app.state.probe_client_factory,
    )
    return ReviewService(plans_service=PlansService(config_bundle=config_bundle, files_service=files_service))


def get_plans_service(
    request: Request,
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> PlansService:
    return PlansService(
        config_bundle=config_bundle,
        files_service=FilesService(
            config_bundle=config_bundle,
            probe_client_factory=request.app.state.probe_client_factory,
        ),
    )


def get_library_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> LibraryService:
    return LibraryService(config_bundle=config_bundle)


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: JobStatus | None = None,
    job_kind: JobKind | None = None,
    file_id: str | None = None,
    worker_name: str | None = None,
    include_cleared: bool = False,
    limit: int | None = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobListResponse:
    del current_user
    jobs = JobsService().list_jobs(
        session,
        status=status,
        job_kind=job_kind,
        tracked_file_id=file_id,
        worker_name=worker_name,
        include_cleared=include_cleared,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobSummaryResponse.from_model(job) for job in jobs],
        limit=limit,
        offset=offset,
    )


@router.get("/progress-stream")
async def stream_job_progress(
    request: Request,
    session_factory=Depends(get_session_factory),
    current_user: User = Depends(require_admin_user),
) -> StreamingResponse:
    del current_user

    async def event_stream():
        last_digest: str | None = None
        while not await request.is_disconnected():
            with session_factory() as session:
                jobs = JobsService().list_jobs(session, limit=100)
                payload = {
                    "items": [
                        json.loads(JobSummaryResponse.from_model(job).model_dump_json())
                        for job in jobs
                        if _is_progress_stream_candidate(job)
                    ],
                }
            digest = json.dumps(payload, sort_keys=True)
            if digest != last_digest:
                last_digest = digest
                yield f"event: jobs\ndata: {digest}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _is_progress_stream_candidate(job) -> bool:
    return job.status in {
        JobStatus.PENDING,
        JobStatus.SCHEDULED,
        JobStatus.RUNNING,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.INTERRUPTED,
        JobStatus.CANCELLED,
        JobStatus.MANUAL_REVIEW,
        JobStatus.SKIPPED,
    }


@router.post("/clear-queue", response_model=BulkJobActionResponse)
def clear_queue(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> BulkJobActionResponse:
    del current_user
    try:
        jobs = JobsService().clear_queue(session)
        session.commit()
        return BulkJobActionResponse(
            status="cleared",
            affected_count=len(jobs),
            affected_job_ids=[job.id for job in jobs],
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/clear-failed", response_model=BulkJobActionResponse)
def clear_failed_jobs(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> BulkJobActionResponse:
    del current_user
    try:
        jobs = JobsService().clear_failed_history(session)
        session.commit()
        return BulkJobActionResponse(
            status="cleared",
            affected_count=len(jobs),
            affected_job_ids=[job.id for job in jobs],
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.get("/backups", response_model=JobBackupListResponse)
def list_job_backups(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobBackupListResponse:
    del current_user
    jobs = JobsService().list_backups(session)
    return JobBackupListResponse(items=[JobBackupResponse.from_model(job) for job in jobs])


@router.delete("/{job_id}/backup", response_model=JobBackupResponse)
def delete_job_backup(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobBackupResponse:
    del current_user
    try:
        job = JobsService().delete_backup(session, job_id=job_id)
        session.commit()
        return JobBackupResponse.from_model(job)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/{job_id}/backup/restore", response_model=JobBackupResponse)
def restore_job_backup(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobBackupResponse:
    del current_user
    try:
        job = JobsService().restore_backup(session, job_id=job_id)
        session.commit()
        return JobBackupResponse.from_model(job)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job_detail(
    job_id: str,
    session: Session = Depends(get_session),
    review_service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> JobDetailResponse:
    del current_user
    try:
        job = JobsService().get_job(session, job_id=job_id)
        detail = JobDetailResponse.from_model(job).model_dump()
        try:
            review_item = review_service.get_item(session, item_id=job.tracked_file_id)
            detail["tracked_file_is_protected"] = review_item.protected_state.is_protected
            detail["requires_review"] = review_item.requires_review
            detail["review_status"] = review_item.review_status
        except ApiServiceError:
            pass
        return JobDetailResponse(**detail)
    except ApiServiceError as error:
        _raise_service_error(error)


@router.get("/{job_id}/artwork")
def get_job_artwork(
    job_id: str,
    session: Session = Depends(get_session),
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    current_user: User = Depends(require_admin_user),
):
    del current_user
    try:
        job = JobsService().get_job(session, job_id=job_id)
    except ApiServiceError as error:
        _raise_service_error(error)
    probe_payload = job.plan_snapshot.probe_snapshot.payload if job.plan_snapshot and job.plan_snapshot.probe_snapshot else {}
    source_path = Path(
        job.tracked_file.source_path
        if job.tracked_file is not None
        else str(probe_payload.get("container", {}).get("file_path") or probe_payload.get("file_path") or "")
    )
    if not source_path.as_posix() or source_path.as_posix() == ".":
        raise HTTPException(status_code=404, detail="Artwork is not available for this job.")
    artwork_path = resolve_job_artwork_path(
        job_id=job.id,
        source_path=source_path,
        ffmpeg_path=config_bundle.app.media.ffmpeg_path,
        cache_dir=config_bundle.app.data_dir / "artwork-cache",
        duration_seconds=(
            job.plan_snapshot.probe_snapshot.payload.get("container", {}).get("duration_seconds")
            if job.plan_snapshot and job.plan_snapshot.probe_snapshot and isinstance(job.plan_snapshot.probe_snapshot.payload, dict)
            else None
        ),
    )
    if artwork_path is None:
        raise HTTPException(status_code=404, detail="Artwork is not available for this job.")
    return FileResponse(artwork_path)


@router.post("", response_model=JobDetailResponse, status_code=201)
def create_job(
    payload: CreateJobRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobDetailResponse:
    del current_user
    try:
        job = JobsService().create_job(
            session,
            tracked_file_id=payload.tracked_file_id,
            plan_snapshot_id=payload.plan_snapshot_id,
            preferred_worker_id=payload.preferred_worker_id,
            pinned_worker_id=payload.pinned_worker_id,
            preferred_backend_override=payload.preferred_backend_override,
            schedule_windows=[item.model_dump(mode="json") for item in payload.schedule_windows],
            backup_policy=payload.backup_policy,
        )
        session.commit()
        return JobDetailResponse.from_model(job)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/{job_id}/retry", response_model=JobDetailResponse, status_code=201)
def retry_job(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobDetailResponse:
    del current_user
    try:
        job = JobsService().retry_job(session, job_id=job_id)
        session.commit()
        return JobDetailResponse.from_model(job)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/{job_id}/cancel", response_model=JobDetailResponse)
def cancel_job(
    job_id: str,
    session: Session = Depends(get_session),
    local_worker_loop: LocalWorkerLoop = Depends(get_local_worker_loop),
    current_user: User = Depends(require_admin_user),
) -> JobDetailResponse:
    del current_user
    try:
        job = JobsService().cancel_job(session, job_id=job_id, local_worker_loop=local_worker_loop)
        session.commit()
        return JobDetailResponse.from_model(job)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


def resolve_job_artwork_path(
    *,
    job_id: str,
    source_path: Path,
    ffmpeg_path: Path | str,
    cache_dir: Path,
    duration_seconds: float | None,
) -> Path | None:
    del job_id, ffmpeg_path, cache_dir, duration_seconds
    return find_local_artwork_sidecar(source_path)


def find_local_artwork_sidecar(source_path: Path) -> Path | None:
    candidates = [
        *[source_path.with_suffix(extension) for extension in ARTWORK_EXTENSIONS],
        *[source_path.with_name(f"{source_path.stem}-poster{extension}") for extension in ARTWORK_EXTENSIONS],
        *[source_path.with_name(f"{source_path.stem}.poster{extension}") for extension in ARTWORK_EXTENSIONS],
        *[source_path.with_name(f"{source_path.stem}-cover{extension}") for extension in ARTWORK_EXTENSIONS],
        *[source_path.parent / f"poster{extension}" for extension in ARTWORK_EXTENSIONS],
        *[source_path.parent / f"folder{extension}" for extension in ARTWORK_EXTENSIONS],
        *[source_path.parent / f"cover{extension}" for extension in ARTWORK_EXTENSIONS],
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


@router.post("/batch", response_model=BatchJobCreateResponse, status_code=201)
def create_batch_jobs(
    payload: CreateBatchJobsRequest,
    session: Session = Depends(get_session),
    plans_service: PlansService = Depends(get_plans_service),
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> BatchJobCreateResponse:
    del current_user
    try:
        scope, source_files = library_service.resolve_selection(
            source_path=payload.source_path,
            folder_path=payload.folder_path,
            selected_paths=payload.selected_paths,
        )
        jobs_service = JobsService()
        items: list[BatchJobItemResponse] = []
        total_files = 0
        created_count = 0
        blocked_count = 0
        schedule_windows = [item.model_dump(mode="json") for item in payload.schedule_windows]
        for source_file in source_files:
            tracked_file, _probe_snapshot, plan_snapshot = plans_service.plan_file(
                session,
                source_path=source_file.as_posix(),
            )
            batch_results = jobs_service.create_batch_jobs(
                session,
                planned_targets=[(source_file.as_posix(), tracked_file, plan_snapshot)],
                preferred_worker_id=payload.preferred_worker_id,
                pinned_worker_id=payload.pinned_worker_id,
                preferred_backend_override=payload.preferred_backend_override,
                schedule_windows=schedule_windows,
                backup_policy=payload.backup_policy,
            )
            for result in batch_results:
                total_files += 1
                if result["status"] == "created":
                    created_count += 1
                elif result["status"] == "blocked":
                    blocked_count += 1
                if not payload.summary_only:
                    items.append(
                        BatchJobItemResponse(
                            source_path=result["source_path"],
                            status=result["status"],
                            message=result["message"],
                            job=JobDetailResponse.from_model(result["job"]) if result["job"] is not None else None,
                        )
                    )
        session.commit()
        return BatchJobCreateResponse(
            scope=scope,
            total_files=total_files,
            created_count=created_count,
            blocked_count=blocked_count,
            items=items,
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@router.post("/dry-run", response_model=DryRunJobCreateResponse, status_code=201)
def create_dry_run_jobs(
    payload: CreateDryRunJobsRequest,
    session: Session = Depends(get_session),
    plans_service: PlansService = Depends(get_plans_service),
    library_service: LibraryService = Depends(get_library_service),
    current_user: User = Depends(require_admin_user),
) -> DryRunJobCreateResponse:
    del current_user
    try:
        pinned_worker = (
            WorkerRepository(session).get_by_id(payload.pinned_worker_id)
            if payload.pinned_worker_id
            else None
        )
        if (
            pinned_worker is not None
            and pinned_worker.schedule_windows
            and not payload.ignore_worker_schedule
            and not schedule_windows_allow_now(pinned_worker.schedule_windows)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "worker_schedule_conflict",
                    "message": "The selected worker is outside its schedule window.",
                    "worker_id": pinned_worker.id,
                    "worker_name": pinned_worker.display_name,
                    "schedule_summary": schedule_windows_summary(pinned_worker.schedule_windows),
                },
            )

        scope, source_files = library_service.resolve_selection(
            source_path=payload.source_path,
            folder_path=payload.folder_path,
            selected_paths=payload.selected_paths,
        )
        planned_targets = []
        for source_file in source_files:
            tracked_file, probe_snapshot, plan_snapshot = plans_service.plan_file(
                session,
                source_path=source_file.as_posix(),
            )
            effective_config_payload = plans_service.serialise_effective_config_bundle(
                source_path=source_file.as_posix(),
                media_file=MediaFile.model_validate(probe_snapshot.payload),
            )
            planned_targets.append(
                (source_file.as_posix(), tracked_file, plan_snapshot, effective_config_payload)
            )
        batch_results = JobsService().create_batch_jobs(
            session,
            planned_targets=[(source_path, tracked_file, plan_snapshot) for source_path, tracked_file, plan_snapshot, _ in planned_targets],
            preferred_worker_id=payload.preferred_worker_id,
            pinned_worker_id=payload.pinned_worker_id,
            preferred_backend_override=payload.preferred_backend_override,
            schedule_windows=(
                [item.model_dump(mode="json") for item in payload.schedule_windows]
                if payload.schedule_windows
                else (pinned_worker.schedule_windows if pinned_worker is not None and not payload.ignore_worker_schedule else None)
            ),
            job_kind=JobKind.DRY_RUN,
            analysis_payload_factory=lambda source_path, tracked_file, plan_snapshot: {
                "mode": "dry_run_request",
                "source_path": source_path,
                "tracked_file_id": tracked_file.id,
                "plan_snapshot_id": plan_snapshot.id,
                "config_bundle": next(
                    config_payload
                    for planned_source_path, _tracked_file, _plan_snapshot, config_payload in planned_targets
                    if planned_source_path == source_path
                ),
            },
            ignore_worker_schedule=payload.ignore_worker_schedule,
        )
        session.commit()
        items = [
            BatchJobItemResponse(
                source_path=result["source_path"],
                status=result["status"],
                message=result["message"],
                job=JobDetailResponse.from_model(result["job"]) if result["job"] is not None else None,
            )
            for result in batch_results
        ]
        return DryRunJobCreateResponse(
            scope=scope,
            total_files=len(items),
            created_count=sum(1 for item in items if item.status == "created"),
            blocked_count=sum(1 for item in items if item.status == "blocked"),
            items=items,
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)
