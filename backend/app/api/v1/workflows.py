import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.workflow import WorkflowCreate, WorkflowRead
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    wf = await WorkflowService.create_workflow(db, data)
    return WorkflowRead.model_validate(wf)


@router.get("/project/{project_id}", response_model=list[WorkflowRead])
async def list_workflows(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRead]:
    workflows = await WorkflowService.list_by_project(db, project_id)
    return [WorkflowRead.model_validate(w) for w in workflows]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    wf = await WorkflowService.get_workflow(db, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowRead.model_validate(wf)
