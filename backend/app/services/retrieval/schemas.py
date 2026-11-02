"""Schemas for ASTRAVA Modular Knowledge Retrieval Engine (M1.3-4).

Defines structured queries, metadata filters, scored results, and context packages
with strict validation, provenance preservation, and budget enforcement.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.artifact import ArtifactType, ArtifactVerificationStatus
from app.models.memory import (
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
)


class MemoryRetrievalFilter(BaseModel):
    """Structured filters for project memory retrieval."""

    model_config = ConfigDict(extra="forbid")

    categories: list[MemoryCategory] | None = None
    provenance_types: list[MemoryProvenanceType] | None = None
    statuses: list[MemoryStatus] | None = None
    is_verified: bool | None = None
    conflict_statuses: list[MemoryConflictStatus] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    source_execution_id: uuid.UUID | None = None
    source_task_id: str | None = None
    source_artifact_id: uuid.UUID | None = None

    # Granular historical inclusion flags
    include_historical: bool = Field(
        default=False,
        description="When False, excludes superseded, rejected, and archived memories by default.",
    )
    include_superseded: bool = Field(
        default=False,
        description="Include superseded memory revisions alongside active memories.",
    )
    include_rejected: bool = Field(
        default=False,
        description="Include rejected memories in candidate retrieval.",
    )
    include_archived: bool = Field(
        default=False,
        description="Include soft-deleted/archived memories in candidate retrieval.",
    )


class ArtifactRetrievalFilter(BaseModel):
    """Structured filters for project artifact retrieval."""

    model_config = ConfigDict(extra="forbid")

    artifact_types: list[ArtifactType] | None = None
    verification_statuses: list[ArtifactVerificationStatus] | None = None
    execution_id: uuid.UUID | None = None
    task_id: str | None = None
    include_lineage: bool = Field(
        default=True,
        description="Whether to traverse and attach ancestor/supersession lineage context.",
    )
    created_after: datetime | None = None
    created_before: datetime | None = None


class RetrievalQuery(BaseModel):
    """Public query contract for project knowledge retrieval."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID = Field(
        ...,
        description="Mandatory project scope. All retrieval operations are strictly isolated by project.",
    )
    query_text: str | None = Field(
        default=None,
        max_length=500,
        description="Search text for PostgreSQL full-text search. Null/empty retrieves by metadata & recency.",
    )
    memory_filter: MemoryRetrievalFilter | None = Field(
        default=None,
        description="Optional structured metadata filters for memories.",
    )
    artifact_filter: ArtifactRetrievalFilter | None = Field(
        default=None,
        description="Optional structured metadata filters for artifacts.",
    )
    top_k_memories: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of memories to return.",
    )
    top_k_artifacts: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum number of artifacts to return.",
    )
    min_relevance_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum composite relevance score threshold.",
    )
    context_budget_chars: int = Field(
        default=4000,
        ge=500,
        le=32000,
        description="Maximum character budget for the formatted context package.",
    )
    include_artifacts: bool = Field(
        default=True,
        description="Whether to include relevant artifacts in the retrieval operation.",
    )

    @field_validator("query_text")
    @classmethod
    def clean_query_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class ScoredMemory(BaseModel):
    """Ranked memory candidate with full scoring explanation."""

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: uuid.UUID
    project_id: uuid.UUID
    category: MemoryCategory
    summary: str
    content: str
    provenance_type: MemoryProvenanceType
    confidence_score: float
    is_verified: bool
    status: MemoryStatus
    revision: int
    previous_revision_id: uuid.UUID | None = None
    conflict_status: MemoryConflictStatus
    conflicting_memory_id: uuid.UUID | None = None
    source_execution_id: uuid.UUID | None = None
    source_task_id: str | None = None
    source_artifact_id: uuid.UUID | None = None
    source_agent_slug: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    # Ranking breakdown
    composite_score: float
    text_score: float
    provenance_weight: float
    verification_weight: float
    recency_weight: float
    status_weight: float
    explanation: str


class ScoredArtifact(BaseModel):
    """Ranked artifact candidate with full scoring explanation and lineage context."""

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: uuid.UUID
    project_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    task_id: str | None = None
    name: str
    file_path: str
    artifact_type: ArtifactType
    mime_type: str
    file_size_bytes: int
    version: int
    parent_artifact_id: uuid.UUID | None = None
    superseded_by_id: uuid.UUID | None = None
    verification_status: ArtifactVerificationStatus
    verification_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    # Lineage information
    ancestors: list[dict[str, Any]] = Field(default_factory=list)
    descendants: list[dict[str, Any]] = Field(default_factory=list)
    superseded_by_name: str | None = None

    # Ranking breakdown
    composite_score: float
    text_score: float
    verification_weight: float
    recency_weight: float
    explanation: str


class ContextAssemblySummary(BaseModel):
    """Summary of bounded context assembly results."""

    model_config = ConfigDict(extra="forbid")

    budget_limit_chars: int
    total_context_chars: int
    memories_included_count: int
    memories_omitted_count: int
    artifacts_included_count: int
    artifacts_omitted_count: int
    budget_exhausted: bool


class RetrievalResult(BaseModel):
    """Traceable, explainable result of a knowledge retrieval operation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: uuid.UUID
    query_text: str | None
    memories: list[ScoredMemory]
    artifacts: list[ScoredArtifact]
    context_package: str
    assembly_summary: ContextAssemblySummary
    total_memories_found: int
    total_artifacts_found: int
    trace_metadata: dict[str, Any] = Field(default_factory=dict)
