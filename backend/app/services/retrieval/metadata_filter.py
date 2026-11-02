"""SQLAlchemy metadata filter generator for ASTRAVA knowledge retrieval.

Builds parameter-safe filter clauses enforcing project isolation and lifecycle governance.
"""

import uuid
from typing import Any

from sqlalchemy import BinaryExpression

from app.models.artifact import Artifact, ArtifactType, ArtifactVerificationStatus
from app.models.memory import (
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.services.retrieval.schemas import (
    ArtifactRetrievalFilter,
    MemoryRetrievalFilter,
)


class MetadataFilter:
    """Builds and validates SQLAlchemy filter expressions for memory and artifact retrieval."""

    @classmethod
    def build_memory_filters(
        cls, project_id: uuid.UUID, filter_spec: MemoryRetrievalFilter | None
    ) -> list[BinaryExpression[Any]]:
        """Constructs SQLAlchemy WHERE clauses for ProjectMemory retrieval.

        Always enforces ProjectMemory.project_id == project_id.
        """
        clauses: list[BinaryExpression[Any]] = [ProjectMemory.project_id == project_id]

        if filter_spec is None:
            # Default behavior: active memories only
            clauses.append(ProjectMemory.status == MemoryStatus.ACTIVE)
            return clauses

        # 1. Lifecycle status resolution
        if filter_spec.statuses is not None:
            valid_statuses = [MemoryStatus(s) for s in filter_spec.statuses]
            clauses.append(ProjectMemory.status.in_(valid_statuses))
        elif filter_spec.include_historical:
            # All statuses allowed
            pass
        else:
            allowed = {MemoryStatus.ACTIVE}
            if filter_spec.include_superseded:
                allowed.add(MemoryStatus.SUPERSEDED)
            if filter_spec.include_rejected:
                allowed.add(MemoryStatus.REJECTED)
            if filter_spec.include_archived:
                allowed.add(MemoryStatus.ARCHIVED)
            clauses.append(ProjectMemory.status.in_(list(allowed)))

        # 2. Categories
        if filter_spec.categories is not None:
            valid_cats = [MemoryCategory(c) for c in filter_spec.categories]
            clauses.append(ProjectMemory.category.in_(valid_cats))

        # 3. Provenance
        if filter_spec.provenance_types is not None:
            valid_prov = [MemoryProvenanceType(p) for p in filter_spec.provenance_types]
            clauses.append(ProjectMemory.provenance_type.in_(valid_prov))

        # 4. Verification
        if filter_spec.is_verified is not None:
            clauses.append(ProjectMemory.is_verified == filter_spec.is_verified)

        # 5. Conflict status
        if filter_spec.conflict_statuses is not None:
            valid_conflicts = [MemoryConflictStatus(c) for c in filter_spec.conflict_statuses]
            clauses.append(ProjectMemory.conflict_status.in_(valid_conflicts))

        # 6. Date boundaries
        if filter_spec.created_after is not None:
            clauses.append(ProjectMemory.created_at >= filter_spec.created_after)
        if filter_spec.created_before is not None:
            clauses.append(ProjectMemory.created_at <= filter_spec.created_before)

        # 7. Entity relationships
        if filter_spec.source_execution_id is not None:
            clauses.append(ProjectMemory.source_execution_id == filter_spec.source_execution_id)
        if filter_spec.source_task_id is not None:
            clauses.append(ProjectMemory.source_task_id == filter_spec.source_task_id)
        if filter_spec.source_artifact_id is not None:
            clauses.append(ProjectMemory.source_artifact_id == filter_spec.source_artifact_id)

        return clauses

    @classmethod
    def build_artifact_filters(
        cls, project_id: uuid.UUID, filter_spec: ArtifactRetrievalFilter | None
    ) -> list[BinaryExpression[Any]]:
        """Constructs SQLAlchemy WHERE clauses for Artifact retrieval.

        Always enforces Artifact.project_id == project_id.
        """
        clauses: list[BinaryExpression[Any]] = [Artifact.project_id == project_id]

        if filter_spec is None:
            return clauses

        if filter_spec.artifact_types is not None:
            valid_types = [ArtifactType(t) for t in filter_spec.artifact_types]
            clauses.append(Artifact.artifact_type.in_(valid_types))

        if filter_spec.verification_statuses is not None:
            valid_verif = [ArtifactVerificationStatus(v) for v in filter_spec.verification_statuses]
            clauses.append(Artifact.verification_status.in_(valid_verif))

        if filter_spec.execution_id is not None:
            clauses.append(Artifact.execution_id == filter_spec.execution_id)

        if filter_spec.task_id is not None:
            clauses.append(Artifact.task_id == filter_spec.task_id)

        if filter_spec.created_after is not None:
            clauses.append(Artifact.created_at >= filter_spec.created_after)

        if filter_spec.created_before is not None:
            clauses.append(Artifact.created_at <= filter_spec.created_before)

        return clauses
