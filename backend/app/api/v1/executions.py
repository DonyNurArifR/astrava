import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.execution import ExecutionStatus
from app.schemas.execution import ExecutionCreate, ExecutionRead
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
