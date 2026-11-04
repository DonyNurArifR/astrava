import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.budget import BudgetReservationStatus, BudgetStatus


class BudgetLimitsUpdate(BaseModel):
    """Partial limit update with mandatory reason and security ceilings."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Mandatory auditable operator reason for adjusting budget limits.",
    )
    max_cost_usd: float | None = Field(default=None, ge=0, le=50.0)
    max_input_tokens: int | None = Field(default=None, ge=0, le=5_000_000)
    max_output_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    max_total_tokens: int | None = Field(default=None, ge=0, le=6_000_000)
    max_agent_attempts: int | None = Field(default=None, ge=0, le=100)
    max_task_attempts: int | None = Field(default=None, ge=0, le=20)
    max_remediation_turns: int | None = Field(default=None, ge=0, le=20)
    max_replan_count: int | None = Field(default=None, ge=0, le=10)
    max_runtime_seconds: int | None = Field(default=None, ge=0, le=7200)


class BudgetConsumedRead(BaseModel):
    cost_usd: float
    actual_cost_usd: float
    estimated_cost_usd: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    runtime_seconds: float
    agent_attempts: int
    remediation_turns: int
    replan_count: int


class BudgetReservedRead(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    active_reservations: int


class BudgetReservationRead(BaseModel):
    """One reservation row. Not part of the summary payload (get_summary returns counts only)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    budget_id: uuid.UUID
    execution_id: uuid.UUID
    reservation_key: str
    purpose: str | None
    agent_slug: str | None
    task_id: str | None
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_usd: float
    reconciled_cost_usd: float | None
    fence_token: str
    attempt_number: int = 0
    status: BudgetReservationStatus
    expires_at: datetime | None
    resolved_at: datetime | None


class BudgetAuditLogRead(BaseModel):
    """One audit log entry for budget limit changes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    budget_id: uuid.UUID
    execution_id: uuid.UUID
    action: str
    actor_id: str
    actor_type: str
    reason: str
    previous_limits: dict[str, Any]
    new_limits: dict[str, Any]
    created_at: datetime


class BudgetSummaryResponse(BaseModel):
    """Mirrors the dict returned by BudgetGovernor.get_summary()."""

    budget_id: uuid.UUID
    execution_id: uuid.UUID
    status: BudgetStatus
    exhaustion_reason: str | None
    is_cost_estimated: bool
    limits: dict[str, float | int | None]
    consumed: BudgetConsumedRead
    reserved: BudgetReservedRead
    remaining: dict[str, float | None]
    utilization: dict[str, float | None]
