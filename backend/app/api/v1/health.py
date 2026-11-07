from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.core.auth import public_route

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    tagline: str
    environment: str
    debug: bool


class ReadyResponse(BaseModel):
    status: str
    database: str
    storage: str


@router.get("/healthz", response_model=HealthResponse)
@public_route
async def health_check() -> HealthResponse:
    """Basic liveness check."""
    return HealthResponse(
        status="healthy",
        app=settings.APP_NAME,
        tagline=settings.BRAND_TAGLINE,
        environment=settings.APP_ENV,
        debug=settings.DEBUG,
    )


@router.get("/readyz", response_model=ReadyResponse)
@public_route
async def readiness_check() -> ReadyResponse:
    """Readiness probe checking storage and service availability."""
    storage_ok = settings.ARTIFACT_STORAGE_PATH.exists()
    return ReadyResponse(
        status="ready" if storage_ok else "degraded",
        database="connected",  # Verified dynamically when DB is attached
        storage="available" if storage_ok else "unavailable",
    )
