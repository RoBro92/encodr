from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_config_bundle,
    get_local_worker_loop,
    get_session,
    get_session_factory,
    get_worker_auth_runtime_settings,
    get_worker_token_service,
    require_admin_user,
    require_authenticated_worker,
)
from app.schemas.worker import (
    QueueHealthSummaryResponse,
    WorkerAssignedJobResponse,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerInventoryDetailResponse,
    WorkerInventoryListResponse,
    WorkerInventorySummaryResponse,
    WorkerJobClaimResponse,
    WorkerJobFailureRequest,
    WorkerJobFailureResponse,
    WorkerJobProgressRequest,
    WorkerJobProgressResponse,
    WorkerJobPollResponse,
    WorkerJobResultRequest,
    WorkerJobResultResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerRunOnceResponse,
    WorkerSelfTestCheckResponse,
    WorkerSelfTestResponse,
    WorkerStateChangeResponse,
    WorkerStatusResponse,
)
from app.services.audit import AuditService
from app.services.errors import ApiServiceError
from app.services.worker import WorkerService
from encodr_core.config import ConfigBundle
from encodr_db.models import User, Worker
from encodr_db.runtime import LocalWorkerLoop

worker_router = APIRouter(prefix="/worker", tags=["worker"])
workers_router = APIRouter(prefix="/workers", tags=["workers"])


def get_worker_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    local_worker_loop: LocalWorkerLoop = Depends(get_local_worker_loop),
    session_factory=Depends(get_session_factory),
    worker_token_service=Depends(get_worker_token_service),
    worker_auth_runtime=Depends(get_worker_auth_runtime_settings),
) -> WorkerService:
    return WorkerService(
        config_bundle=config_bundle,
        local_worker_loop=local_worker_loop,
        session_factory=session_factory,
        worker_token_service=worker_token_service,
        worker_auth_runtime=worker_auth_runtime,
        audit_service=AuditService(),
    )


def _raise_service_error(error: ApiServiceError) -> None:
    headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
    raise HTTPException(status_code=error.status_code, detail=str(error), headers=headers) from error


@worker_router.post("/register", response_model=WorkerRegistrationResponse, status_code=201)
def register_worker(
    payload: WorkerRegistrationRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
) -> WorkerRegistrationResponse:
    try:
        registration = service.register_worker(
            session,
            worker_key=payload.worker_key,
            display_name=payload.display_name,
            worker_type=payload.worker_type,
            registration_secret=payload.registration_secret,
            capability_summary=payload.capability_summary.model_dump(mode="json"),
            host_summary=payload.host_summary.model_dump(mode="json"),
            runtime_summary=payload.runtime_summary.model_dump(mode="json") if payload.runtime_summary is not None else None,
            binary_summary=[item.model_dump(mode="json") for item in payload.binary_summary],
            health_status=payload.health_status,
            health_summary=payload.health_summary,
            request=request,
        )
        session.commit()
        return WorkerRegistrationResponse(**registration)
    except ApiServiceError as error:
        if error.status_code == 401:
            session.commit()
        else:
            session.rollback()
        _raise_service_error(error)


@worker_router.post("/heartbeat", response_model=WorkerHeartbeatResponse)
def heartbeat_worker(
    payload: WorkerHeartbeatRequest,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerHeartbeatResponse:
    try:
        heartbeat = service.heartbeat(
            session,
            worker=current_worker,
            capability_summary=payload.capability_summary.model_dump(mode="json") if payload.capability_summary is not None else None,
            host_summary=payload.host_summary.model_dump(mode="json") if payload.host_summary is not None else None,
            runtime_summary=payload.runtime_summary.model_dump(mode="json") if payload.runtime_summary is not None else None,
            binary_summary=[item.model_dump(mode="json") for item in payload.binary_summary],
            health_status=payload.health_status,
            health_summary=payload.health_summary,
        )
        session.commit()
        return WorkerHeartbeatResponse(**heartbeat)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/jobs/request", response_model=WorkerJobPollResponse)
def request_remote_job(
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerJobPollResponse:
    try:
        payload = service.request_job(session, worker=current_worker)
        session.commit()
        if payload["job"] is not None:
            payload["job"] = WorkerAssignedJobResponse(**payload["job"])
        return WorkerJobPollResponse(**payload)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/jobs/{job_id}/claim", response_model=WorkerJobClaimResponse)
def claim_remote_job(
    job_id: str,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerJobClaimResponse:
    try:
        payload = service.claim_job(session, worker=current_worker, job_id=job_id)
        session.commit()
        return WorkerJobClaimResponse(**payload)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/jobs/{job_id}/progress", response_model=WorkerJobProgressResponse)
def report_remote_job_progress(
    job_id: str,
    payload: WorkerJobProgressRequest,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerJobProgressResponse:
    try:
        response = service.report_job_progress(
            session,
            worker=current_worker,
            job_id=job_id,
            stage=payload.stage,
            percent=payload.percent,
            out_time_seconds=payload.out_time_seconds,
            fps=payload.fps,
            speed=payload.speed,
            runtime_summary=payload.runtime_summary.model_dump(mode="json") if payload.runtime_summary is not None else None,
        )
        session.commit()
        return WorkerJobProgressResponse(**response)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/jobs/{job_id}/failure", response_model=WorkerJobFailureResponse)
def report_remote_job_failure(
    job_id: str,
    payload: WorkerJobFailureRequest,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerJobFailureResponse:
    try:
        response = service.report_job_failure(
            session,
            worker=current_worker,
            job_id=job_id,
            failure_message=payload.failure_message,
            failure_category=payload.failure_category,
            runtime_summary=payload.runtime_summary.model_dump(mode="json") if payload.runtime_summary is not None else None,
        )
        session.commit()
        return WorkerJobFailureResponse(**response)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/jobs/{job_id}/result", response_model=WorkerJobResultResponse)
def submit_remote_job_result(
    job_id: str,
    payload: WorkerJobResultRequest,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_worker: Worker = Depends(require_authenticated_worker),
) -> WorkerJobResultResponse:
    try:
        response = service.submit_job_result(
            session,
            worker=current_worker,
            job_id=job_id,
            result_payload=payload.result_payload,
            runtime_summary=payload.runtime_summary.model_dump(mode="json") if payload.runtime_summary is not None else None,
        )
        session.commit()
        return WorkerJobResultResponse(**response)
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@worker_router.post("/run-once", response_model=WorkerRunOnceResponse, dependencies=[Depends(require_admin_user)])
def run_worker_once(
    worker_service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerRunOnceResponse:
    del current_user
    summary = worker_service.run_once()
    return WorkerRunOnceResponse(
        processed_job=summary.processed_job,
        job_id=summary.job_id,
        final_status=summary.final_status,
        failure_message=summary.failure_message,
        started_at=summary.started_at,
        completed_at=summary.completed_at,
    )


@worker_router.get("/status", response_model=WorkerStatusResponse, dependencies=[Depends(require_admin_user)])
def get_worker_status(
    worker_service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerStatusResponse:
    del current_user
    payload = worker_service.status_summary()
    payload["queue_health"] = QueueHealthSummaryResponse(**payload["queue_health"])
    return WorkerStatusResponse(**payload)


@worker_router.post("/self-test", response_model=WorkerSelfTestResponse, dependencies=[Depends(require_admin_user)])
def run_worker_self_test(
    worker_service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerSelfTestResponse:
    del current_user
    payload = worker_service.self_test()
    payload["checks"] = [
        WorkerSelfTestCheckResponse(**check)
        for check in payload["checks"]
    ]
    return WorkerSelfTestResponse(**payload)


@workers_router.get("", response_model=WorkerInventoryListResponse, dependencies=[Depends(require_admin_user)])
def list_workers(
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerInventoryListResponse:
    del current_user
    items = service.list_worker_inventory(session)
    return WorkerInventoryListResponse(
        items=[WorkerInventorySummaryResponse(**item) for item in items]
    )


@workers_router.get("/{worker_id}", response_model=WorkerInventoryDetailResponse, dependencies=[Depends(require_admin_user)])
def get_worker(
    worker_id: str,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerInventoryDetailResponse:
    del current_user
    try:
        item = service.get_worker_inventory_item(session, worker_id=worker_id)
        return WorkerInventoryDetailResponse(**item)
    except ApiServiceError as error:
        _raise_service_error(error)


@workers_router.post("/{worker_id}/enable", response_model=WorkerStateChangeResponse, dependencies=[Depends(require_admin_user)])
def enable_worker(
    worker_id: str,
    request: Request,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerStateChangeResponse:
    try:
        worker = service.set_remote_worker_enabled(
            session,
            worker_id=worker_id,
            enabled=True,
            actor=current_user,
            request=request,
        )
        session.commit()
        return WorkerStateChangeResponse(
            worker=WorkerInventoryDetailResponse(**worker),
            status="enabled",
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)


@workers_router.post("/{worker_id}/disable", response_model=WorkerStateChangeResponse, dependencies=[Depends(require_admin_user)])
def disable_worker(
    worker_id: str,
    request: Request,
    session: Session = Depends(get_session),
    service: WorkerService = Depends(get_worker_service),
    current_user: User = Depends(require_admin_user),
) -> WorkerStateChangeResponse:
    try:
        worker = service.set_remote_worker_enabled(
            session,
            worker_id=worker_id,
            enabled=False,
            actor=current_user,
            request=request,
        )
        session.commit()
        return WorkerStateChangeResponse(
            worker=WorkerInventoryDetailResponse(**worker),
            status="disabled",
        )
    except ApiServiceError as error:
        session.rollback()
        _raise_service_error(error)
