import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    @staticmethod
    async def create(db: AsyncSession, data: TaskCreate) -> Task:
        task = Task(
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            executor_type=data.executor_type,
            assigned_model=data.assigned_model,
            risk_level=data.risk_level,
            priority=data.priority,
            dependency_ids=data.dependency_ids,
            input_data=data.input_data,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: uuid.UUID) -> Task | None:
        stmt = select(Task).where(Task.id == task_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_project(
        db: AsyncSession, project_id: uuid.UUID, status: TaskStatus | None = None
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.priority.asc(), Task.created_at.asc())
        )
        if status:
            stmt = stmt.where(Task.status == status)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update(db: AsyncSession, task_id: uuid.UUID, data: TaskUpdate) -> Task | None:
        task = await TaskService.get_by_id(db, task_id)
        if not task:
            return None

        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(task, key, value)

        await db.flush()
        await db.refresh(task)
        return task
