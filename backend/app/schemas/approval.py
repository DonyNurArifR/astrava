import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.approval import ApprovalStatus
from app.models.task import RiskLevel


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalStatus  # APPROVED or REJECTED
    reason: str | None = Field(None, max_length=2000, description="Operator rationale")
    # Optional and advisory only: the server derives the approver identity from the
    # authenticated operator. A value that differs from it is rejected with 403.
    decided_by: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Approver display name (must match operator)",
    )


class ApprovalRead(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    task_id: uuid.UUID | None
    action_type: str
    description: str
    risk_level: RiskLevel
    status: ApprovalStatus
    context_data: dict[str, Any]
    decision_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
