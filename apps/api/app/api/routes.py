from fastapi import APIRouter

from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.config import router as config_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.review import router as review_router
from app.api.system import router as system_router
from app.api.worker import worker_router, workers_router


router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(analytics_router)
router.include_router(files_router)
router.include_router(jobs_router)
router.include_router(review_router)
router.include_router(worker_router)
router.include_router(workers_router)
router.include_router(system_router)
router.include_router(config_router)
