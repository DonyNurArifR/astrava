import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.project import ProjectStatus, StudioType


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200, description="Project display name")
    description: str | None = Field(
        None, max_length=2000, description="Project summary description"
    )
    studio_type: StudioType = StudioType.SAAS
    target_objectives: list[str] = []
    settings_json: dict[str, Any] = {}
    repo_path: str | None = Field(None, max_length=500, description="Local Git repository path")
    base_branch: str | None = Field(
        "main", max_length=100, description="Base branch for execution worktrees"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("Project name must contain at least 2 non-whitespace characters")
        return stripped


class ProjectCreate(ProjectBase):
    workspace_id: uuid.UUID | None = None  # Auto-assigned if single workspace


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    status: ProjectStatus | None = None
    target_objectives: list[str] | None = None
    settings_json: dict[str, Any] | None = None
    repo_path: str | None = Field(None, max_length=500)
    base_branch: str | None = Field(None, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 2:
                raise ValueError("Project name must contain at least 2 non-whitespace characters")
            return stripped
        return v


class ProjectRead(ProjectBase):
    id: uuid.UUID
    workspace_id: uuid.UUID
    slug: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
