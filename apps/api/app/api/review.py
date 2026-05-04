from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_config_bundle, get_session, require_admin_user
from app.schemas.jobs import JobDetailResponse
from app.schemas.review import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewItemDetailResponse,
    ReviewItemSummaryResponse,
    ReviewListResponse,
)
from app.services.audit import AuditService
from app.services.diagnostics import exception_fields
from app.services.errors import ApiServiceError
from app.services.review import ReviewService
from encodr_core.config import ConfigBundle
from encodr_db.models import User

router = APIRouter(
    prefix="/review",
    tags=["review"],
    dependencies=[Depends(require_admin_user)],
)
logger = logging.getLogger("encodr.api.review")


def get_review_service(
    config_bundle: ConfigBundle = Depends(get_config_bundle),
) -> ReviewService:
    return ReviewService(config_bundle=config_bundle, audit_service=AuditService())


def _raise_service_error(error: ApiServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=str(error)) from error


def _log_service_error(event: str, error: ApiServiceError, **fields: object) -> None:
    extra = {
        "event": event,
        "status": error.status_code,
        **exception_fields(error),
        **{key: value for key, value in fields.items() if value is not None},
    }
    if error.status_code >= 500:
        logger.error("API action failed", extra=extra)
    else:
        logger.warning("API action failed", extra=extra)


@router.get("/items", response_model=ReviewListResponse)
def list_review_items(
    status: str | None = None,
    protected_only: bool | None = None,
    is_4k: bool | None = None,
    recent_failures_only: bool = False,
    limit: int | None = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewListResponse:
    del current_user
    items = service.list_items(
        session,
        status=status,
        protected_only=protected_only,
        is_4k=is_4k,
        recent_failures_only=recent_failures_only,
        limit=limit,
        offset=offset,
    )
    return ReviewListResponse(
        items=[service.to_summary_response(item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get("/items/{item_id}", response_model=ReviewItemDetailResponse)
def get_review_item(
    item_id: str,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewItemDetailResponse:
    del current_user
    try:
        item = service.get_item(session, item_id=item_id)
        return service.to_detail_response(item)
    except ApiServiceError as error:
        _log_service_error("api_review_item_detail_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)


@router.post("/items/{item_id}/approve", response_model=ReviewDecisionResponse)
def approve_review_item(
    item_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewDecisionResponse:
    try:
        item, decision, job = service.approve_item(
            session,
            item_id=item_id,
            note=payload.note,
            actor=current_user,
            request=request,
        )
        session.commit()
        return ReviewDecisionResponse(
            review_item=service.to_detail_response(item),
            decision=service._decision_summary(decision),
            job=JobDetailResponse.from_model(job) if job is not None else None,
        )
    except ApiServiceError as error:
        session.rollback()
        _log_service_error("api_review_approve_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)


@router.post("/items/{item_id}/reject", response_model=ReviewDecisionResponse)
def reject_review_item(
    item_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewDecisionResponse:
    try:
        item, decision, job = service.reject_item(
            session,
            item_id=item_id,
            note=payload.note,
            actor=current_user,
            request=request,
        )
        session.commit()
        return ReviewDecisionResponse(
            review_item=service.to_detail_response(item),
            decision=service._decision_summary(decision),
            job=JobDetailResponse.from_model(job),
        )
    except ApiServiceError as error:
        session.rollback()
        _log_service_error("api_review_reject_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)


@router.post("/items/{item_id}/hold", response_model=ReviewDecisionResponse)
def hold_review_item(
    item_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewDecisionResponse:
    try:
        item, decision = service.hold_item(
            session,
            item_id=item_id,
            note=payload.note,
            actor=current_user,
            request=request,
        )
        session.commit()
        return ReviewDecisionResponse(
            review_item=service.to_detail_response(item),
            decision=service._decision_summary(decision),
        )
    except ApiServiceError as error:
        session.rollback()
        _log_service_error("api_review_hold_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)


@router.post("/items/{item_id}/mark-protected", response_model=ReviewDecisionResponse)
def mark_review_item_protected(
    item_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewDecisionResponse:
    try:
        item, decision = service.mark_protected(
            session,
            item_id=item_id,
            note=payload.note,
            actor=current_user,
            request=request,
        )
        session.commit()
        return ReviewDecisionResponse(
            review_item=service.to_detail_response(item),
            decision=service._decision_summary(decision),
        )
    except ApiServiceError as error:
        session.rollback()
        _log_service_error("api_review_mark_protected_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)


@router.post("/items/{item_id}/clear-protected", response_model=ReviewDecisionResponse)
def clear_review_item_protected(
    item_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    session: Session = Depends(get_session),
    service: ReviewService = Depends(get_review_service),
    current_user: User = Depends(require_admin_user),
) -> ReviewDecisionResponse:
    try:
        item, decision = service.clear_protected(
            session,
            item_id=item_id,
            note=payload.note,
            actor=current_user,
            request=request,
        )
        session.commit()
        return ReviewDecisionResponse(
            review_item=service.to_detail_response(item),
            decision=service._decision_summary(decision),
        )
    except ApiServiceError as error:
        session.rollback()
        _log_service_error("api_review_clear_protected_failed", error, tracked_file_id=item_id, file_id=item_id)
        _raise_service_error(error)
