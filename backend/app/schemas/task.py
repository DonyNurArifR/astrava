import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.task import ExecutorType, RiskLevel, TaskStatus


class TaskBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=300, description="Task title")
    description: str | None = Field(None, max_length=5000, description="Task details")
    executor_type: ExecutorType = ExecutorType.CLAUDE_CODE
    assigned_model: str = "claude-haiku-5-5"
    assigned_agent_slug: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    priority: int = 1
    dependency_ids: list[str] = []
    input_data: dict[str, Any] = {}

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("Task title must contain at least 2 non-whitespace characters")
        return stripped


class TaskCreate(TaskBase):
    project_id: uuid.UUID


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=300)
    description: str | None = Field(None, max_length=5000)
    status: TaskStatus | None = None
    output_data: dict[str, Any] | None = None
    error_details: str | None = None
    remediation_history_json: list[dict[str, Any]] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 2:
                raise ValueError("Task title must contain at least 2 non-whitespace characters")
            return stripped
        return v


class TaskRead(TaskBase):
    id: uuid.UUID
    project_id: uuid.UUID
    status: TaskStatus
    output_data: dict[str, Any]
    error_details: str | None = None
    remediation_history_json: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime

    @field_validator("remediation_history_json", mode="before")
    @classmethod
    def default_remediation_history(cls, v: Any) -> list[dict[str, Any]]:
        return v if v is not None else []

    model_config = ConfigDict(from_attributes=True)
