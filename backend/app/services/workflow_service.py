import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution import ExecutionEvent, ExecutionStatus, WorkflowExecution
from app.models.workflow import Workflow, WorkflowStatus
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate


class WorkflowService:
    @staticmethod
    async def create_workflow(db: AsyncSession, data: WorkflowCreate) -> Workflow:
        workflow = Workflow(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            studio_type=data.studio_type,
            status=WorkflowStatus.ACTIVE,
            step_definitions=data.step_definitions,
            total_steps=len(data.step_definitions),
        )
        db.add(workflow)
        await db.flush()
        await db.refresh(workflow)
        return workflow

    @staticmethod
    async def get_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
        stmt = select(Workflow).where(Workflow.id == workflow_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_project(db: AsyncSession, project_id: uuid.UUID) -> list[Workflow]:
        stmt = (
            select(Workflow)
            .where(Workflow.project_id == project_id)
            .order_by(Workflow.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_execution(db: AsyncSession, data: ExecutionCreate) -> WorkflowExecution:
        execution = WorkflowExecution(
            workflow_id=data.workflow_id,
            project_id=data.project_id,
            status=ExecutionStatus.PENDING,
            current_step=0,
            state_data=data.initial_state,
        )
        db.add(execution)
        await db.flush()
        await db.refresh(execution)
        return execution

    @staticmethod
    async def get_execution(db: AsyncSession, execution_id: uuid.UUID) -> WorkflowExecution | None:
        stmt = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id)
            .options(selectinload(WorkflowExecution.events))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_executions(
        db: AsyncSession,
        project_id: uuid.UUID | None = None,
        status: ExecutionStatus | None = None,
        limit: int = 50,
    ) -> list[WorkflowExecution]:
        stmt = select(WorkflowExecution).order_by(WorkflowExecution.created_at.desc())
        if project_id:
            stmt = stmt.where(WorkflowExecution.project_id == project_id)
        if status:
            stmt = stmt.where(WorkflowExecution.status == status)
        stmt = stmt.limit(limit).options(selectinload(WorkflowExecution.events))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def record_event(
        db: AsyncSession, execution_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> ExecutionEvent:
        event = ExecutionEvent(
            execution_id=execution_id,
            event_type=event_type,
            payload=payload,
        )
        db.add(event)
        await db.flush()
        return event

    @staticmethod
    async def list_events(db: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionEvent]:
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.created_at.asc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def update_execution_status(
        db: AsyncSession,
        execution_id: uuid.UUID,
        status: ExecutionStatus,
        error_message: str | None = None,
        state_data: dict[str, Any] | None = None,
        checkpoint_id: str | None = None,
        current_step: int | None = None,
    ) -> WorkflowExecution | None:
        execution = await WorkflowService.get_execution(db, execution_id)
        if not execution:
            return None

        execution.status = status
        if current_step is not None:
            execution.current_step = current_step
        if status == ExecutionStatus.RUNNING and not execution.started_at:
            execution.started_at = datetime.now(UTC)
        elif status in [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ]:
            execution.completed_at = datetime.now(UTC)

        if error_message:
            execution.error_message = error_message
        if state_data is not None:
            execution.state_data = state_data
            if "replan_count" in state_data:
                execution.replan_count = int(state_data.get("replan_count") or 0)
            if "goal_id" in state_data and state_data["goal_id"]:
                gid = state_data["goal_id"]
                execution.goal_id = uuid.UUID(gid) if isinstance(gid, str) else gid
        if checkpoint_id:
            execution.checkpoint_id = checkpoint_id

        await db.flush()
        await db.refresh(execution)
        return execution
