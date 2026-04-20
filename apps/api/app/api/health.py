from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.dependencies import require_current_user
from encodr_db.models import User

router = APIRouter(tags=["system"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@router.get("/health/authenticated")
def authenticated_healthcheck(current_user: User = Depends(require_current_user)) -> dict[str, str]:
    return {"status": "ok", "service": "api", "username": current_user.username}
