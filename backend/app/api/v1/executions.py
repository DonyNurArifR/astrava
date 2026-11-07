import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OperatorContext, require_authorized_verifier
from app.db.session import get_db
from app.models.execution import ExecutionStatus
from app.orchestrator.planner import DAGModifier
from app.schemas.budget import BudgetLimitsUpdate, BudgetSummaryResponse
from app.schemas.execution import ExecutionCreate, ExecutionRead
from app.schemas.remediation import RemediationSummaryResponse
from app.services.budget_governor import BudgetGovernor, BudgetGovernorError
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/executions", tags=["Executions"])


@router.post("", response_model=ExecutionRead, status_code=status.HTTP_201_CREATED)
async def create_execution(
    data: ExecutionCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> ExecutionRead:
    execution = await WorkflowService.create_execution(db, data)
    await WorkflowService.record_event(
        db, execution.id, "execution_created", {"created_by": operator.actor_id}
    )
    await db.commit()
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
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> ExecutionRead:
    execution = await WorkflowService.update_execution_status(
        db, execution_id, ExecutionStatus.PAUSED
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    await WorkflowService.record_event(
        db,
        execution_id,
        "execution_paused",
        {"reason": "Manual operator pause", "actor_id": operator.actor_id},
    )
    await db.commit()
    return ExecutionRead.model_validate(execution)


@router.post("/{execution_id}/resume", response_model=ExecutionRead)
async def resume_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> ExecutionRead:
    execution = await WorkflowService.update_execution_status(
        db, execution_id, ExecutionStatus.RUNNING
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    await WorkflowService.record_event(
        db,
        execution_id,
        "execution_resumed",
        {"reason": "Manual operator resume", "actor_id": operator.actor_id},
    )
    await db.commit()
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


@router.get("/{execution_id}/remediations", response_model=RemediationSummaryResponse)
async def get_execution_remediations(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RemediationSummaryResponse:
    execution = await WorkflowService.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    events = await WorkflowService.list_events(db, execution_id)
    remediation_events = [e for e in events if e.event_type == "task_remediation_cycle"]
    cycles = [e.payload for e in remediation_events]
    tasks_affected = list({c.get("task_id") for c in cycles if c.get("task_id")})

    return RemediationSummaryResponse(
        execution_id=execution_id,
        total_remediations=execution.remediation_count or len(cycles),
        tasks_affected=tasks_affected,
        cycles=cycles,
    )


class ReplanExecutionRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Justification for replanning")
    new_tasks: list[dict[str, Any]] | None = None


@router.post("/{execution_id}/replan", response_model=ExecutionRead)
async def replan_execution(
    execution_id: uuid.UUID,
    data: ReplanExecutionRequest,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> ExecutionRead:
    execution = await WorkflowService.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot replan an execution in status '{execution.status}'",
        )

    # Record replan in budget governor (enforcing max_replan_count)
    try:
        await BudgetGovernor.record_replan(db, execution_id)
    except BudgetGovernorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state_data = dict(execution.state_data or {})
    current_tasks = state_data.get("tasks", [])
    completed_ids = state_data.get("completed_task_ids", [])
    failed_ids = state_data.get("failed_task_ids", [])

    if data.new_tasks:
        try:
            updated_tasks = DAGModifier.modify_dag(
                current_tasks=current_tasks,
                completed_task_ids=completed_ids,
                failed_task_ids=failed_ids,
                new_or_modified_tasks=data.new_tasks,
            )
            state_data["tasks"] = updated_tasks
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid replan DAG: {exc}") from exc

    state_data["replan_needed"] = True
    state_data["replan_reason"] = data.reason
    state_data["replan_count"] = (execution.replan_count or 0) + 1

    execution.replan_count = state_data["replan_count"]
    execution.state_data = state_data

    await WorkflowService.record_event(
        db,
        execution_id,
        "execution_replan_requested",
        {
            "reason": data.reason,
            "replan_count": execution.replan_count,
            "actor_id": operator.actor_id,
        },
    )
    await db.commit()
    await db.refresh(execution)
    return ExecutionRead.model_validate(execution)
