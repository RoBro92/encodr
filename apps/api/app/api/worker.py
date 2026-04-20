from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.dependencies import get_config_bundle, get_local_worker_loop, require_admin_user
from app.schemas.worker import BinaryStatusResponse, WorkerRunOnceResponse, WorkerStatusResponse
from app.services.worker import WorkerService
from encodr_core.config import ConfigBundle
from encodr_db.models import User
from encodr_db.runtime import LocalWorkerLoop

router = APIRouter(
    prefix="/worker",
    tags=["worker"],
    dependencies=[Depends(require_admin_user)],
)


def get_worker_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    local_worker_loop: LocalWorkerLoop = Depends(get_local_worker_loop),
) -> WorkerService:
    return WorkerService(config_bundle=config_bundle, local_worker_loop=local_worker_loop)


@router.post("/run-once", response_model=WorkerRunOnceResponse)
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


@router.get("/status", response_model=WorkerStatusResponse)
def get_worker_status(
    worker_service: WorkerService = Depends(get_worker_service),
    config_bundle: ConfigBundle = Depends(get_config_bundle),
    local_worker_loop: LocalWorkerLoop = Depends(get_local_worker_loop),
    current_user: User = Depends(require_admin_user),
) -> WorkerStatusResponse:
    del current_user
    ffmpeg = BinaryStatusResponse(**worker_service.binary_status(config_bundle.app.media.ffmpeg_path))
    ffprobe = BinaryStatusResponse(**worker_service.binary_status(config_bundle.app.media.ffprobe_path))
    snapshot = local_worker_loop.status_tracker.snapshot()
    return WorkerStatusResponse(
        worker_name=local_worker_loop.worker_name,
        local_only=True,
        default_queue=config_bundle.workers.default_queue,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        local_worker_enabled=config_bundle.workers.local.enabled,
        local_worker_queue=config_bundle.workers.local.queue,
        last_run_started_at=snapshot.last_run_started_at,
        last_run_completed_at=snapshot.last_run_completed_at,
        last_processed_job_id=snapshot.last_processed_job_id,
        last_result_status=snapshot.last_result_status,
        last_failure_message=snapshot.last_failure_message,
        processed_jobs=snapshot.processed_jobs,
        capabilities=config_bundle.workers.local.capabilities.model_dump(mode="json"),
    )
