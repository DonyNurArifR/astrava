import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.usage import ModelExecutionStatus


class ModelExecutionCreate(BaseModel):
    execution_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    provider: str
    model: str
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    exit_code: int = 0
    status: ModelExecutionStatus = ModelExecutionStatus.SUCCESS
    raw_metrics: dict[str, Any] = {}


class ModelExecutionRead(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID | None
    task_id: uuid.UUID | None
    provider: str
    model: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    exit_code: int
    status: ModelExecutionStatus
    raw_metrics: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UsageSummary(BaseModel):
    total_executions: int
    successful_executions: int
    failed_executions: int
    total_duration_ms: int
    total_tokens: int
    total_cost_usd: float
