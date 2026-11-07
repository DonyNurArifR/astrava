import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OperatorContext, require_authorized_verifier
from app.db.session import get_db
from app.models.goal import GoalStatus
from app.orchestrator.runner import OrchestrationRunner
from app.schemas.execution import ExecutionRead
from app.schemas.goal import GoalCreate, GoalRead, GoalUpdate
from app.services.goal_service import GoalService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/goals", tags=["goals"])


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(
    project_id: uuid.UUID,
    data: GoalCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> GoalRead:
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    goal = await GoalService.create_goal(db, project_id, data)
    return GoalRead.model_validate(goal)


@router.get("", response_model=list[GoalRead])
async def list_goals(
    project_id: uuid.UUID,
    status_filter: GoalStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[GoalRead]:
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    goals = await GoalService.list_goals_by_project(db, project_id, status=status_filter)
    for g in goals:
        await GoalService.recalculate_progress(db, g.id)
    return [GoalRead.model_validate(g) for g in goals]


@router.get("/{goal_id}", response_model=GoalRead)
async def get_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> GoalRead:
    goal = await GoalService.get_goal(db, goal_id)
    if not goal or goal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Goal not found")

    await GoalService.recalculate_progress(db, goal_id)
    return GoalRead.model_validate(goal)


@router.patch("/{goal_id}", response_model=GoalRead)
async def update_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    data: GoalUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> GoalRead:
    goal = await GoalService.get_goal(db, goal_id)
    if not goal or goal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Goal not found")

    updated = await GoalService.update_goal(db, goal_id, data)
    return GoalRead.model_validate(updated)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> None:
    goal = await GoalService.get_goal(db, goal_id)
    if not goal or goal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Goal not found")

    await GoalService.delete_goal(db, goal_id)


@router.post(
    "/{goal_id}/execute", response_model=ExecutionRead, status_code=status.HTTP_202_ACCEPTED
)
async def execute_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: OperatorContext = Depends(require_authorized_verifier),
) -> ExecutionRead:
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    goal = await GoalService.get_goal(db, goal_id)
    if not goal or goal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Goal not found")

    execution = await OrchestrationRunner.start_pipeline(
        db=db,
        project_id=project_id,
        objective=f"{goal.title}: {goal.description}",
        studio_type=project.studio_type.value if hasattr(project, "studio_type") else "saas",
        goal_id=goal_id,
    )
    return ExecutionRead.model_validate(execution)
