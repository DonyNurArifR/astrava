import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.task import ExecutorType, RiskLevel, TaskStatus


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    executor_type: ExecutorType = ExecutorType.CLAUDE_CODE
    assigned_model: str = "claude-haiku-5-5"
    risk_level: RiskLevel = RiskLevel.LOW
    priority: int = 1
    dependency_ids: list[str] = []
    input_data: dict[str, Any] = {}


class TaskCreate(TaskBase):
    project_id: uuid.UUID


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    output_data: dict[str, Any] | None = None
    error_details: str | None = None


class TaskRead(TaskBase):
    id: uuid.UUID
    project_id: uuid.UUID
    status: TaskStatus
    output_data: dict[str, Any]
    error_details: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
