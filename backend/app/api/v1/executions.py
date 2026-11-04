import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OperatorContext, require_authorized_verifier
from app.db.session import get_db
from app.models.execution import ExecutionStatus
from app.schemas.budget import BudgetLimitsUpdate, BudgetSummaryResponse
from app.schemas.execution import ExecutionCreate, ExecutionRead
from app.services.budget_governor import BudgetGovernor, BudgetGovernorError
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/executions", tags=["Executions"])


@router.post("", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
async def create_execution(
    data: ExecutionCreate,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    execution = await WorkflowService.create_execution(db, data)
    return ExecutionRead.model_validate(execution)


@router.get("", response_model=list[ExecutionRead])
async def list_executions(
    project_id: uuid.UUID | None = None,
    status: ExecutionStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionRead]:
    executions = await WorkflowService.list_executions(
        db, project_id=project_id, status=status, limit=limit
    )
    return [ExecutionRead.model_validate(e) for e in executions]


@router.get("/{execution_id}", response_model=ExecutionRead)
async def get_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    execution = await WorkflowService.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionRead.model_validate(execution)


@router.post("/{execution_id}/pause", response_model=ExecutionRead)
async def pause_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    execution = await WorkflowService.update_execution_status(
        db, execution_id, ExecutionStatus.PAUSED
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    await WorkflowService.record_event(
        db, execution_id, "execution_paused", {"reason": "Manual operator pause"}
    )
    return ExecutionRead.model_validate(execution)


@router.post("/{execution_id}/resume", response_model=ExecutionRead)
async def resume_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    execution = await WorkflowService.update_execution_status(
        db, execution_id, ExecutionStatus.RUNNING
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    await WorkflowService.record_event(
        db, execution_id, "execution_resumed", {"reason": "Manual operator resume"}
    )
    return ExecutionRead.model_validate(execution)


@router.get("/{execution_id}/budget", response_model=BudgetSummaryResponse)
async def get_execution_budget(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BudgetSummaryResponse:
    if await BudgetGovernor.get_budget(db, execution_id) is None:
        raise HTTPException(status_code=404, detail="Budget not found for execution")
    summary = await BudgetGovernor.get_summary(db, execution_id)
    return BudgetSummaryResponse(**summary)


@router.post("/{execution_id}/budget/increase", response_model=BudgetSummaryResponse)
async def increase_execution_budget(
    execution_id: uuid.UUID,
    data: BudgetLimitsUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> BudgetSummaryResponse:
    execution = await WorkflowService.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    if await BudgetGovernor.get_budget(db, execution_id) is None:
        raise HTTPException(status_code=404, detail="Budget not found for execution")

    limits_dict = data.model_dump(exclude_unset=True, exclude={"reason"})
    try:
        await BudgetGovernor.increase_budget(
            db,
            execution_id,
            new_limits=limits_dict,
            actor_id=operator.actor_id,
            actor_type=operator.actor_type,
            reason=data.reason,
        )
        await WorkflowService.record_event(
            db,
            execution_id,
            "pipeline_budget_increased",
            {
                "actor_id": operator.actor_id,
                "reason": data.reason,
                "updated_limits": {
                    k: float(v) if hasattr(v, "__float__") else v for k, v in limits_dict.items()
                },
            },
        )
        await db.commit()
    except BudgetGovernorError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    summary = await BudgetGovernor.get_summary(db, execution_id)
    return BudgetSummaryResponse(**summary)
