import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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
    state_data: dict[str, Any]
    checkpoint_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[ExecutionEventRead] = []

    model_config = ConfigDict(from_attributes=True)
