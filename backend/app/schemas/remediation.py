"""ASTRAVA V1.4: Schemas for Automated Remediation Telemetry (M1.4-3)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemediationCycleRead(BaseModel):
    cycle: int
    task_id: str
    diagnostics: str = ""
    unmet_criteria: list[str] = Field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RemediationSummaryResponse(BaseModel):
    execution_id: uuid.UUID
    total_remediations: int
    tasks_affected: list[str] = Field(default_factory=list)
    cycles: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
