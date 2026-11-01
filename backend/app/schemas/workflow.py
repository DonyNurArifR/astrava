import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.workflow import WorkflowStatus


class WorkflowBase(BaseModel):
    name: str
    description: str | None = None
    studio_type: str = "saas"
    step_definitions: list[dict[str, Any]] = []


class WorkflowCreate(WorkflowBase):
    project_id: uuid.UUID


class WorkflowRead(WorkflowBase):
    id: uuid.UUID
    project_id: uuid.UUID
    status: WorkflowStatus
    total_steps: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
