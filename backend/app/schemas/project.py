import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.project import ProjectStatus, StudioType


class ProjectBase(BaseModel):
    name: str
    description: str | None = None
    studio_type: StudioType = StudioType.SAAS
    target_objectives: list[str] = []
    settings_json: dict[str, Any] = {}


class ProjectCreate(ProjectBase):
    workspace_id: uuid.UUID | None = None  # Auto-assigned if single workspace


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    target_objectives: list[str] | None = None
    settings_json: dict[str, Any] | None = None


class ProjectRead(ProjectBase):
    id: uuid.UUID
    workspace_id: uuid.UUID
    slug: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
