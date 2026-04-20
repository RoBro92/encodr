from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_config_bundle, get_session, require_admin_user
from app.schemas.jobs import CreateJobRequest, JobDetailResponse, JobListResponse, JobSummaryResponse
from app.services.errors import ApiServiceError
from app.services.files import FilesService
from app.services.jobs import JobsService
from app.services.plans import PlansService
from app.services.review import ReviewService
from encodr_core.config import ConfigBundle
from encodr_db.models import JobStatus, User

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_admin_user)],
)


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


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: JobStatus | None = None,
    file_id: str | None = None,
    worker_name: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin_user),
) -> JobListResponse:
    del current_user
    jobs = JobsService().list_jobs(
        session,
        status=status,
        tracked_file_id=file_id,
        worker_name=worker_name,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[JobSummaryResponse.from_model(job) for job in jobs],
        limit=limit,
        offset=offset,
    )


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
