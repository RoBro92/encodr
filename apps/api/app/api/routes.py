from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "api"}

