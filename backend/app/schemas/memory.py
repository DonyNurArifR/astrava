"""Pydantic v2 schemas for project memory, audit logs, and conflict resolution."""

import uuid
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
)

T = TypeVar("T")


class MemoryCreateRequest(BaseModel):
    """Request payload to create a new project memory.

    Note: Clients cannot directly set is_verified or verified_at on creation.
    Verification must proceed through explicit verification flows.
    """

    category: MemoryCategory
    summary: str = Field(..., min_length=1, max_length=500, description="Concise memory summary")
    content: str = Field(..., min_length=1, description="Full factual memory content")
    provenance_type: MemoryProvenanceType = Field(
        default=MemoryProvenanceType.USER_PROVIDED,
        description="Source provenance classification",
    )
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score; defaults to provenance policy weight if omitted",
    )
    source_execution_id: uuid.UUID | None = None
    source_task_id: str | None = None
    source_artifact_id: uuid.UUID | None = None
    source_agent_slug: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("summary must not be empty or whitespace-only.")
        if len(cleaned) > 500:
            raise ValueError("summary must be at most 500 characters.")
        return cleaned

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("content must not be empty or whitespace-only.")
        return cleaned


class MemoryUpdateRequest(BaseModel):
    """Request payload to update an existing memory.

    Enforces optimistic concurrency via expected_revision.
    Creates an immutable new revision row; historical revisions remain preserved.
    """

    expected_revision: int = Field(
        ...,
        ge=1,
        description="Expected current revision number for optimistic concurrency protection",
    )
    summary: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None, min_length=1)
    metadata_json: dict[str, Any] | None = None
    reason: str | None = Field(None, description="Reason for the revision update")


class MemoryActionRequest(BaseModel):
    """Request payload for simple lifecycle transitions (archive, restore)."""

    reason: str | None = Field(None, description="Optional reason for the lifecycle transition")


class MemoryVerifyRequest(BaseModel):
    """Request payload to mark a memory as verified."""

    verified_by: str | None = Field(
        None,
        description="Optional verifier label. Server enforces authenticated operator context.",
    )
    verification_details: dict[str, Any] | None = Field(
        default=None,
        description="Structured verification evidence, test run IDs, or review details",
    )
    reason: str | None = Field(None, description="Verification reason or approval notes")

    @field_validator("verified_by")
    @classmethod
    def validate_verified_by(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("verified_by cannot be empty or whitespace only")
        return cleaned


class MemoryConflictResolveRequest(BaseModel):
    """Request payload to resolve a detected memory conflict."""

    resolution: Literal["supersede", "reject", "merge"] = Field(
        ...,
        description="Resolution strategy: supersede (keep this row, supersede partner), "
        "reject (reject this row, keep partner), or merge (synthesize into new revision)",
    )
    reason: str = Field(..., min_length=1, description="Mandatory resolution justification")
    actor_id: str | None = Field(None, description="Identifier of the resolving operator")
    merged_summary: str | None = Field(
        None,
        max_length=500,
        description="Synthesized summary required if resolution is 'merge'",
    )
    merged_content: str | None = Field(
        None,
        description="Synthesized content required if resolution is 'merge'",
    )


class MemoryRead(BaseModel):
    """Public read schema for a ProjectMemory record."""

    id: uuid.UUID
    project_id: uuid.UUID
    category: MemoryCategory
    summary: str
    content: str
    provenance_type: MemoryProvenanceType
    confidence_score: float
    is_verified: bool
    verified_at: datetime | None = None
    source_execution_id: uuid.UUID | None = None
    source_task_id: str | None = None
    source_artifact_id: uuid.UUID | None = None
    source_agent_slug: str | None = None
    status: MemoryStatus
    revision: int
    previous_revision_id: uuid.UUID | None = None
    conflict_status: MemoryConflictStatus
    conflicting_memory_id: uuid.UUID | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoryConflictItem(BaseModel):
    """Public representation of a detected conflict item with partner memory details."""

    memory_id: uuid.UUID
    summary: str
    category: MemoryCategory
    status: MemoryStatus
    revision: int
    provenance_type: MemoryProvenanceType
    conflict_status: MemoryConflictStatus
    conflicting_memory_id: uuid.UUID | None = None
    partner_summary: str | None = None
    partner_status: MemoryStatus | None = None
    partner_provenance_type: MemoryProvenanceType | None = None
    partner_revision: int | None = None
    created_at: datetime


class MemoryAuditLogRead(BaseModel):
    """Public read schema for an immutable MemoryAuditLog entry."""

    id: uuid.UUID
    memory_id: uuid.UUID | None = None
    project_id: uuid.UUID
    action: MemoryAuditAction
    actor_type: str
    actor_id: str | None = None
    reason: str | None = None
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse[T](BaseModel):
    """Standardized bounded paginated container."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class MemoryStatsResponse(BaseModel):
    """Aggregate statistics for a project's memory bank."""

    total_active: int = 0
    verified_findings: int = 0
    agent_conclusions: int = 0
    assumptions: int = 0
    open_conflicts: int = 0
    archived: int = 0
