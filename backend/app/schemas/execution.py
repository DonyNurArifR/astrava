import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.execution import ExecutionStatus


class ExecutionEventRead(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionBase(BaseModel):
    workflow_id: uuid.UUID
    project_id: uuid.UUID


class ExecutionCreate(ExecutionBase):
    initial_state: dict[str, Any] = {}


class ExecutionRead(ExecutionBase):
    id: uuid.UUID
    status: ExecutionStatus
    current_step: int
    remediation_count: int = 0
    replan_count: int = 0
    goal_id: uuid.UUID | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None
    state_data: dict[str, Any]
    checkpoint_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[ExecutionEventRead] = []

    @field_validator("remediation_count", "replan_count", mode="before")
    @classmethod
    def default_int_counts(cls, v: Any) -> int:
        return v if v is not None else 0

    model_config = ConfigDict(from_attributes=True)
