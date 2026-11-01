import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.project import StudioType
from app.orchestrator.planner import PlannerService, StructuredPlan
from app.orchestrator.runner import OrchestrationRunner
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.execution import ExecutionRead
from app.services.project_service import ProjectService

router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])


class PlanRequest(BaseModel):
    project_id: uuid.UUID
    objective: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Target goal or requirements for the autonomous plan",
    )
    studio_type: StudioType = StudioType.SAAS

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("Objective must contain at least 3 non-whitespace characters")
        return stripped


class ExecutePipelineRequest(BaseModel):
    project_id: uuid.UUID
    objective: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Target goal or requirements for autonomous pipeline execution",
    )
    studio_type: StudioType = StudioType.SAAS

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("Objective must contain at least 3 non-whitespace characters")
        return stripped


@router.post("/plan", response_model=StructuredPlan)
async def generate_plan(
    req: PlanRequest,
    db: AsyncSession = Depends(get_db),
) -> StructuredPlan:
    project = await ProjectService.get_by_id(db, req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return PlannerService.generate_plan(
        project_id=str(req.project_id),
        objective=req.objective,
        studio_type=req.studio_type,
    )


@router.post("/execute", response_model=ExecutionRead, status_code=status.HTTP_202_ACCEPTED)
async def execute_pipeline(
    req: ExecutePipelineRequest,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    project = await ProjectService.get_by_id(db, req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    execution = await OrchestrationRunner.start_pipeline(
        db=db,
        project_id=req.project_id,
        objective=req.objective,
        studio_type=req.studio_type.value,
    )
    return ExecutionRead.model_validate(execution)


@router.post("/resume/{execution_id}", response_model=ExecutionRead)
async def resume_pipeline(
    execution_id: uuid.UUID,
    decision_req: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
) -> ExecutionRead:
    try:
        execution = await OrchestrationRunner.resume_pipeline(
            db=db,
            execution_id=execution_id,
            decision_req=decision_req,
        )
        return ExecutionRead.model_validate(execution)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
