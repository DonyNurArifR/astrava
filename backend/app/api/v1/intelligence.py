from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.usage import ModelExecutionRead, UsageSummary
from app.services.usage_service import UsageService

router = APIRouter(prefix="/intelligence", tags=["Intelligence & Usage"])


@router.get("/usage", response_model=list[ModelExecutionRead])
async def list_model_executions(
    limit: int = Query(50, ge=1, le=100),
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ModelExecutionRead]:
    records = await UsageService.list_executions(db, limit=limit, provider=provider)
    return [ModelExecutionRead.model_validate(r) for r in records]


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    db: AsyncSession = Depends(get_db),
) -> UsageSummary:
    return await UsageService.get_summary(db)
