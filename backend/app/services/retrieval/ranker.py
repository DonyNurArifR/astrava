"""Deterministic, multi-signal ranking engine for ASTRAVA knowledge retrieval.

Implements transparent scoring incorporating:
1. PostgreSQL text relevance.
2. Provenance policy weights.
3. Verification status separation.
4. Lifecycle status weighting.
5. Half-life recency decay.
6. Stable, deterministic tie-breakers.
"""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.artifact import Artifact, ArtifactVerificationStatus
from app.models.memory import (
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.services.retrieval.schemas import ScoredArtifact, ScoredMemory

PROVENANCE_WEIGHTS: dict[MemoryProvenanceType, float] = {
    MemoryProvenanceType.USER_PROVIDED: 1.00,
    MemoryProvenanceType.VERIFIED_FINDING: 0.95,
    MemoryProvenanceType.AGENT_CONCLUSION: 0.70,
    MemoryProvenanceType.ASSUMPTION: 0.50,
}

STATUS_WEIGHTS: dict[MemoryStatus, float] = {
    MemoryStatus.ACTIVE: 1.00,
    MemoryStatus.PROPOSED: 0.90,
    MemoryStatus.SUPERSEDED: 0.20,
    MemoryStatus.REJECTED: 0.20,
    MemoryStatus.ARCHIVED: 0.20,
}

ARTIFACT_VERIFICATION_WEIGHTS: dict[ArtifactVerificationStatus, float] = {
    ArtifactVerificationStatus.VERIFIED: 1.00,
    ArtifactVerificationStatus.UNVERIFIED: 0.85,
    ArtifactVerificationStatus.FAILED: 0.20,
}


class RetrievalRanker:
    """Computes deterministic relevance scores for memories and artifacts."""

    @staticmethod
    def calculate_recency_factor(
        created_at: datetime, reference_time: datetime | None = None
    ) -> float:
        """Calculates exponential recency factor with a 30-day half-life.

        Returns a value in [0.80, 1.00].
        """
        now = reference_time or datetime.now(UTC)
        if created_at.tzinfo is None:
            # Handle naive datetime as UTC
            c_at = created_at.replace(tzinfo=UTC)
        else:
            c_at = created_at

        delta_days = max(0.0, (now - c_at).total_seconds() / 86400.0)
        # 30-day half-life decay bounded to [0.80, 1.00]
        decay = math.exp(-delta_days / 30.0)
        return round(0.80 + 0.20 * decay, 4)

    @classmethod
    def score_memory(
        cls,
        memory: ProjectMemory,
        text_score: float | None = None,
        reference_time: datetime | None = None,
    ) -> ScoredMemory:
        """Scores a ProjectMemory candidate deterministically."""
        prov_wt = PROVENANCE_WEIGHTS.get(memory.provenance_type, 0.50)
        verif_wt = 1.00 if memory.is_verified else 0.90
        status_wt = STATUS_WEIGHTS.get(memory.status, 0.20)
        recency_wt = cls.calculate_recency_factor(memory.created_at, reference_time)

        # Baseline metadata quality score (always in [0.0, 1.0])
        quality_score = 0.40 * prov_wt + 0.30 * verif_wt + 0.20 * recency_wt + 0.10 * status_wt

        if text_score is not None:
            # Bounded text relevance gating: text relevance dominates ranking
            # so irrelevant documents cannot rank high regardless of provenance.
            bounded_text = max(0.0, min(1.0, text_score))
            composite = round(bounded_text * quality_score, 4)
            explanation = (
                f"text={bounded_text:.3f} * (0.4*prov={prov_wt:.2f} + 0.3*verif={verif_wt:.2f} "
                f"+ 0.2*recency={recency_wt:.2f} + 0.1*status={status_wt:.2f}) -> {composite:.4f}"
            )
            raw_text = bounded_text
        else:
            # Empty query: pure metadata & recency ranking
            composite = round(quality_score, 4)
            explanation = (
                f"metadata_only: 0.4*prov={prov_wt:.2f} + 0.3*verif={verif_wt:.2f} "
                f"+ 0.2*recency={recency_wt:.2f} + 0.1*status={status_wt:.2f} -> {composite:.4f}"
            )
            raw_text = 1.0

        now = reference_time or datetime.now(UTC)
        mem_id = memory.id or uuid.uuid4()
        c_at = memory.created_at or now
        u_at = memory.updated_at or c_at
        conflict_st = memory.conflict_status or MemoryConflictStatus.NONE

        return ScoredMemory(
            id=mem_id,
            project_id=memory.project_id,
            category=memory.category,
            summary=memory.summary,
            content=memory.content,
            provenance_type=memory.provenance_type,
            confidence_score=memory.confidence_score,
            is_verified=memory.is_verified,
            status=memory.status,
            revision=memory.revision,
            previous_revision_id=memory.previous_revision_id,
            conflict_status=conflict_st,
            conflicting_memory_id=memory.conflicting_memory_id,
            source_execution_id=memory.source_execution_id,
            source_task_id=memory.source_task_id,
            source_artifact_id=memory.source_artifact_id,
            source_agent_slug=memory.source_agent_slug,
            created_at=c_at,
            updated_at=u_at,
            metadata_json=memory.metadata_json or {},
            composite_score=composite,
            text_score=raw_text,
            provenance_weight=prov_wt,
            verification_weight=verif_wt,
            recency_weight=recency_wt,
            status_weight=status_wt,
            explanation=explanation,
        )

    @classmethod
    def score_artifact(
        cls,
        artifact: Artifact,
        text_score: float | None = None,
        lineage_context: dict[str, Any] | None = None,
        reference_time: datetime | None = None,
    ) -> ScoredArtifact:
        """Scores an Artifact candidate deterministically."""
        verif_wt = ARTIFACT_VERIFICATION_WEIGHTS.get(artifact.verification_status, 0.85)
        recency_wt = cls.calculate_recency_factor(artifact.created_at, reference_time)
        quality_score = 0.60 * verif_wt + 0.40 * recency_wt

        if text_score is not None:
            bounded_text = max(0.0, min(1.0, text_score))
            composite = round(bounded_text * quality_score, 4)
            explanation = (
                f"text={bounded_text:.3f} * (0.6*verif={verif_wt:.2f} + 0.4*recency={recency_wt:.2f}) "
                f"-> {composite:.4f}"
            )
            raw_text = bounded_text
        else:
            composite = round(quality_score, 4)
            explanation = (
                f"metadata_only: 0.6*verif={verif_wt:.2f} + 0.4*recency={recency_wt:.2f} "
                f"-> {composite:.4f}"
            )
            raw_text = 1.0

        ancestors_data: list[dict[str, Any]] = []
        descendants_data: list[dict[str, Any]] = []
        superseded_by_name: str | None = None

        if lineage_context:
            for anc in lineage_context.get("ancestors", []):
                ancestors_data.append({"id": str(anc.id), "name": anc.name, "version": anc.version})
            for desc in lineage_context.get("descendants", []):
                descendants_data.append(
                    {"id": str(desc.id), "name": desc.name, "version": desc.version}
                )
            if lineage_context.get("superseded_by"):
                superseded_by_name = lineage_context["superseded_by"].name

        now = reference_time or datetime.now(UTC)
        art_id = artifact.id or uuid.uuid4()
        c_at = artifact.created_at or now
        u_at = artifact.updated_at or c_at

        return ScoredArtifact(
            id=art_id,
            project_id=artifact.project_id,
            execution_id=artifact.execution_id,
            task_id=artifact.task_id,
            name=artifact.name,
            file_path=artifact.file_path,
            artifact_type=artifact.artifact_type,
            mime_type=artifact.mime_type,
            file_size_bytes=artifact.file_size_bytes,
            version=artifact.version,
            parent_artifact_id=artifact.parent_artifact_id,
            superseded_by_id=artifact.superseded_by_id,
            verification_status=artifact.verification_status,
            verification_details=artifact.verification_details or {},
            created_at=c_at,
            updated_at=u_at,
            ancestors=ancestors_data,
            descendants=descendants_data,
            superseded_by_name=superseded_by_name,
            composite_score=composite,
            text_score=raw_text,
            verification_weight=verif_wt,
            recency_weight=recency_wt,
            explanation=explanation,
        )

    @staticmethod
    def sort_memories(candidates: list[ScoredMemory]) -> list[ScoredMemory]:
        """Sorts memories deterministically: composite score desc, created_at desc, id asc."""
        return sorted(
            candidates,
            key=lambda m: (
                -m.composite_score,
                -m.created_at.timestamp(),
                str(m.id),
            ),
        )

    @staticmethod
    def sort_artifacts(candidates: list[ScoredArtifact]) -> list[ScoredArtifact]:
        """Sorts artifacts deterministically: composite score desc, created_at desc, id asc."""
        return sorted(
            candidates,
            key=lambda a: (
                -a.composite_score,
                -a.created_at.timestamp(),
                str(a.id),
            ),
        )
