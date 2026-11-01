import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.approval import ApprovalStatus
from app.models.task import RiskLevel


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalStatus  # APPROVED or REJECTED
    reason: str | None = None
    decided_by: str = "Abstract"


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
