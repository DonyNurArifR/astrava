import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval, ApprovalStatus
from app.models.task import RiskLevel


class ApprovalService:
    @staticmethod
    async def request_approval(
        db: AsyncSession,
        execution_id: uuid.UUID,
        action_type: str,
        description: str,
        risk_level: RiskLevel,
        task_id: uuid.UUID | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> Approval:
        approval = Approval(
            execution_id=execution_id,
            task_id=task_id,
            action_type=action_type,
            description=description,
            risk_level=risk_level,
            status=ApprovalStatus.PENDING,
            context_data=context_data or {},
        )
        db.add(approval)
        await db.flush()
        await db.refresh(approval)
        return approval

    @staticmethod
    async def get_by_id(db: AsyncSession, approval_id: uuid.UUID) -> Approval | None:
        stmt = select(Approval).where(Approval.id == approval_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_pending(db: AsyncSession) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_all(db: AsyncSession, limit: int = 50) -> list[Approval]:
        stmt = select(Approval).order_by(Approval.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def decide(
        db: AsyncSession,
        approval_id: uuid.UUID,
        status: ApprovalStatus,
        reason: str | None = None,
        decided_by: str = "Abstract",
    ) -> Approval | None:
        approval = await ApprovalService.get_by_id(db, approval_id)
        if not approval:
            return None

        approval.status = status
        approval.decision_reason = reason
        approval.decided_by = decided_by
        approval.decided_at = datetime.now(UTC)

        await db.flush()
        await db.refresh(approval)
        return approval
