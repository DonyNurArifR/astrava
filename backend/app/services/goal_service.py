import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionStatus, WorkflowExecution
from app.models.goal import GoalStatus, ProjectGoal
from app.schemas.goal import GoalCreate, GoalUpdate

logger = logging.getLogger("astrava.goals")


class GoalService:
    @staticmethod
    async def create_goal(db: AsyncSession, project_id: uuid.UUID, data: GoalCreate) -> ProjectGoal:
        goal = ProjectGoal(
            project_id=project_id,
            title=data.title,
            description=data.description,
            target_criteria=data.target_criteria,
            status=GoalStatus.ACTIVE,
            progress_percentage=0.0,
        )
        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        return goal

    @staticmethod
    async def get_goal(db: AsyncSession, goal_id: uuid.UUID) -> ProjectGoal | None:
        stmt = select(ProjectGoal).where(ProjectGoal.id == goal_id)
        result = await db.scalars(stmt)
        return result.first()

    @staticmethod
    async def list_goals_by_project(
        db: AsyncSession, project_id: uuid.UUID, status: GoalStatus | None = None
    ) -> list[ProjectGoal]:
        stmt = (
            select(ProjectGoal)
            .where(ProjectGoal.project_id == project_id)
            .order_by(ProjectGoal.created_at.desc())
        )
        if status:
            stmt = stmt.where(ProjectGoal.status == status)
        result = await db.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def update_goal(
        db: AsyncSession, goal_id: uuid.UUID, data: GoalUpdate
    ) -> ProjectGoal | None:
        goal = await GoalService.get_goal(db, goal_id)
        if not goal:
            return None

        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(goal, key, value)

        await db.commit()
        await db.refresh(goal)
        return goal

    @staticmethod
    async def delete_goal(db: AsyncSession, goal_id: uuid.UUID) -> bool:
        goal = await GoalService.get_goal(db, goal_id)
        if not goal:
            return False

        await db.delete(goal)
        await db.commit()
        return True

    @staticmethod
    async def recalculate_progress(db: AsyncSession, goal_id: uuid.UUID) -> float:
        """Computes goal completion percentage based on tasks completed in linked executions."""
        goal = await GoalService.get_goal(db, goal_id)
        if not goal:
            return 0.0

        stmt = select(WorkflowExecution).where(WorkflowExecution.goal_id == goal_id)
        executions = (await db.scalars(stmt)).all()
        if not executions:
            return goal.progress_percentage

        total_tasks = 0
        completed_tasks = 0

        for exc in executions:
            state_data = exc.state_data or {}
            tasks = state_data.get("tasks", [])
            total_tasks += len(tasks)
            completed_tasks += len(state_data.get("completed_task_ids", []))

        if total_tasks == 0:
            percentage = (
                100.0 if any(e.status == ExecutionStatus.COMPLETED for e in executions) else 0.0
            )
        else:
            percentage = round(min(100.0, max(0.0, (completed_tasks / total_tasks) * 100.0)), 1)

        goal.progress_percentage = percentage
        if percentage >= 100.0 and goal.status == GoalStatus.ACTIVE:
            goal.status = GoalStatus.ACHIEVED

        await db.commit()
        await db.refresh(goal)
        return percentage
