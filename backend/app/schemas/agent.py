import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import StudioType


class AgentBase(BaseModel):
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., max_length=200)
    description: str
    studio_type: StudioType
    capabilities: list[str] = Field(default_factory=list)
    instructions: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    available_tools: list[str] = Field(default_factory=list)
    model_config_data: dict[str, Any] = Field(
        default_factory=lambda: {"model_id": "claude-haiku-5-5", "temperature": 0.2}
    )
    execution_config: dict[str, Any] = Field(
        default_factory=lambda: {"timeout_seconds": 120, "max_retries": 1}
    )
    verification_requirements: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", max_length=50)
    is_enabled: bool = True


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    capabilities: list[str] | None = None
    instructions: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    available_tools: list[str] | None = None
    model_config_data: dict[str, Any] | None = None
    execution_config: dict[str, Any] | None = None
    verification_requirements: list[str] | None = None
    version: str | None = None
    is_enabled: bool | None = None


class AgentStatusUpdate(BaseModel):
    is_enabled: bool


class AgentRead(AgentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentMetricsResponse(BaseModel):
    agent_slug: str
    agent_name: str
    studio_type: StudioType
    total_tasks_assigned: int
    completed_tasks: int
    failed_tasks: int
    success_rate: float
    total_remediations: int
    total_cost_usd: float
    total_tokens: int
    avg_duration_ms: float
