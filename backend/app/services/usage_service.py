from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import ModelExecution, ModelExecutionStatus
from app.schemas.usage import ModelExecutionCreate, UsageSummary


class UsageService:
    @staticmethod
    async def record_execution(db: AsyncSession, data: ModelExecutionCreate) -> ModelExecution:
        record = ModelExecution(
            execution_id=data.execution_id,
            task_id=data.task_id,
            provider=data.provider,
            model=data.model,
            duration_ms=data.duration_ms,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            cache_read_tokens=data.cache_read_tokens,
            cache_creation_tokens=data.cache_creation_tokens,
            cost_usd=data.cost_usd,
            exit_code=data.exit_code,
            status=data.status,
            raw_metrics=data.raw_metrics,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    @staticmethod
    async def list_executions(
        db: AsyncSession,
        limit: int = 50,
        provider: str | None = None,
    ) -> list[ModelExecution]:
        stmt = select(ModelExecution).order_by(ModelExecution.created_at.desc())
        if provider:
            stmt = stmt.where(ModelExecution.provider == provider)
        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_summary(db: AsyncSession) -> UsageSummary:
        total_execs = await db.scalar(select(func.count(ModelExecution.id))) or 0
        success_execs = (
            await db.scalar(
                select(func.count(ModelExecution.id)).where(
                    ModelExecution.status == ModelExecutionStatus.SUCCESS
                )
            )
            or 0
        )
        failed_execs = (
            await db.scalar(
                select(func.count(ModelExecution.id)).where(
                    ModelExecution.status != ModelExecutionStatus.SUCCESS
                )
            )
            or 0
        )
        total_duration = await db.scalar(select(func.sum(ModelExecution.duration_ms))) or 0
        total_in_tokens = await db.scalar(select(func.sum(ModelExecution.input_tokens))) or 0
        total_out_tokens = await db.scalar(select(func.sum(ModelExecution.output_tokens))) or 0
        total_cost = await db.scalar(select(func.sum(ModelExecution.cost_usd))) or 0.0

        return UsageSummary(
            total_executions=total_execs,
            successful_executions=success_execs,
            failed_executions=failed_execs,
            total_duration_ms=int(total_duration),
            total_tokens=int(total_in_tokens + total_out_tokens),
            total_cost_usd=float(total_cost),
        )
