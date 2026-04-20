from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_config_bundle, get_session, require_admin_user
from app.schemas.analytics import (
    AnalyticsDashboardResponse,
    AnalyticsMediaResponse,
    AnalyticsOutcomesResponse,
    AnalyticsOverviewResponse,
    AnalyticsStorageResponse,
    RecentAnalyticsResponse,
)
from app.services.analytics import AnalyticsService
from encodr_core.config import ConfigBundle
from encodr_db.models import User

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_admin_user)],
)


def get_analytics_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> AnalyticsService:
    return AnalyticsService(config_bundle=config_bundle)


@router.get("/overview", response_model=AnalyticsOverviewResponse)
def get_analytics_overview(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> AnalyticsOverviewResponse:
    del current_user
    return service.overview(session)


@router.get("/storage", response_model=AnalyticsStorageResponse)
def get_analytics_storage(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> AnalyticsStorageResponse:
    del current_user
    return service.storage(session)


@router.get("/outcomes", response_model=AnalyticsOutcomesResponse)
def get_analytics_outcomes(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> AnalyticsOutcomesResponse:
    del current_user
    return service.outcomes(session)


@router.get("/media", response_model=AnalyticsMediaResponse)
def get_analytics_media(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> AnalyticsMediaResponse:
    del current_user
    return service.media(session)


@router.get("/recent", response_model=RecentAnalyticsResponse)
def get_analytics_recent(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> RecentAnalyticsResponse:
    del current_user
    return service.recent(session)


@router.get("/dashboard", response_model=AnalyticsDashboardResponse)
def get_analytics_dashboard(
    session: Session = Depends(get_session),
    service: AnalyticsService = Depends(get_analytics_service),
    current_user: User = Depends(require_admin_user),
) -> AnalyticsDashboardResponse:
    del current_user
    return service.dashboard(session)
