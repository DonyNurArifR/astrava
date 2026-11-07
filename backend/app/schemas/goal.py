import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.goal import GoalStatus


class GoalBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255, description="High-level goal title")
    description: str = Field(..., min_length=2, description="Detailed goal description")
    target_criteria: list[str] = Field(default_factory=list, description="Target success criteria")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("Goal title must contain at least 2 non-whitespace characters")
        return stripped


class GoalCreate(GoalBase):
    pass


class GoalUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    status: GoalStatus | None = None
    target_criteria: list[str] | None = None
    progress_percentage: float | None = Field(None, ge=0.0, le=100.0)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 2:
                raise ValueError("Goal title must contain at least 2 non-whitespace characters")
            return stripped
        return v


class GoalRead(GoalBase):
    id: uuid.UUID
    project_id: uuid.UUID
    status: GoalStatus
    progress_percentage: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
