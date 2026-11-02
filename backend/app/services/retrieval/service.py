"""Public orchestration service for ASTRAVA knowledge retrieval (M1.3-4).

Coordinates query processing, project-isolated candidate retrieval, multi-signal ranking,
and bounded context package assembly.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.memory import ProjectMemory
from app.services.artifact_intelligence_service import ArtifactIntelligenceService
from app.services.retrieval.artifact_retriever import ArtifactRetriever
from app.services.retrieval.context_assembler import ContextAssembler
from app.services.retrieval.memory_retriever import MemoryRetriever
from app.services.retrieval.query_processor import QueryProcessor
from app.services.retrieval.ranker import RetrievalRanker
from app.services.retrieval.schemas import (
    ArtifactRetrievalFilter,
    MemoryRetrievalFilter,
    RetrievalQuery,
    RetrievalResult,
    ScoredArtifact,
    ScoredMemory,
)


class RetrievalService:
    """Public orchestration interface for project knowledge retrieval."""

    @classmethod
    async def search(cls, db: AsyncSession, query: RetrievalQuery) -> RetrievalResult:
        """Executes a full knowledge retrieval operation.

        Enforces project isolation at the API boundary, performs PostgreSQL full-text
        and metadata search, scores candidates deterministically, and formats a
        strictly bounded context package.
        """
        start_time = time.perf_counter()
        now = datetime.now(UTC)

        # 1. Query sanitization & processing
        processed_query = QueryProcessor.process(query.query_text)

        # 2. Retrieve memories
        memories = await MemoryRetriever.retrieve(
            db=db,
            project_id=query.project_id,
            processed_query=processed_query,
            filter_spec=query.memory_filter,
            top_k=query.top_k_memories,
            min_threshold=query.min_relevance_threshold,
            reference_time=now,
        )

        # 3. Retrieve artifacts (if requested)
        artifacts: list[ScoredArtifact] = []
        if query.include_artifacts and query.top_k_artifacts > 0:
            artifacts = await ArtifactRetriever.retrieve(
                db=db,
                project_id=query.project_id,
                processed_query=processed_query,
                filter_spec=query.artifact_filter,
                top_k=query.top_k_artifacts,
                min_threshold=query.min_relevance_threshold,
                reference_time=now,
            )

        # 4. Assemble bounded context package
        context_pkg, summary = ContextAssembler.assemble(
            memories=memories,
            artifacts=artifacts,
            budget_chars=query.context_budget_chars,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        trace_meta: dict[str, Any] = {
            "elapsed_ms": elapsed_ms,
            "query_normalized": processed_query.normalized_text,
            "tokens_extracted": processed_query.tokens,
            "is_empty_query": processed_query.is_empty,
            "memory_filters_applied": (
                query.memory_filter.model_dump(exclude_none=True) if query.memory_filter else None
            ),
            "artifact_filters_applied": (
                query.artifact_filter.model_dump(exclude_none=True)
                if query.artifact_filter
                else None
            ),
            "budget_limit_chars": query.context_budget_chars,
            "context_package_chars": summary.total_context_chars,
        }

        return RetrievalResult(
            project_id=query.project_id,
            query_text=query.query_text,
            memories=memories,
            artifacts=artifacts,
            context_package=context_pkg,
            assembly_summary=summary,
            total_memories_found=len(memories),
            total_artifacts_found=len(artifacts),
            trace_metadata=trace_meta,
        )

    @classmethod
    async def retrieve_context_package(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        query_text: str | None = None,
        memory_filter: MemoryRetrievalFilter | None = None,
        artifact_filter: ArtifactRetrievalFilter | None = None,
        budget_chars: int = 4000,
        top_k_memories: int = 20,
        top_k_artifacts: int = 10,
    ) -> str:
        """Convenience method returning strictly the bounded Markdown context package."""
        query = RetrievalQuery(
            project_id=project_id,
            query_text=query_text,
            memory_filter=memory_filter,
            artifact_filter=artifact_filter,
            context_budget_chars=budget_chars,
            top_k_memories=top_k_memories,
            top_k_artifacts=top_k_artifacts,
        )
        res = await cls.search(db, query)
        return res.context_package

    @classmethod
    async def get_memory_by_id(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> ScoredMemory | None:
        """Retrieves a single memory strictly scoped by project_id."""
        stmt = select(ProjectMemory).where(
            ProjectMemory.id == memory_id,
            ProjectMemory.project_id == project_id,
        )
        result = await db.execute(stmt)
        mem = result.scalar_one_or_none()
        if mem is None:
            return None
        return RetrievalRanker.score_memory(mem, text_score=None)

    @classmethod
    async def get_artifact_by_id(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        include_lineage: bool = True,
    ) -> ScoredArtifact | None:
        """Retrieves a single artifact strictly scoped by project_id with optional lineage."""
        stmt = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.project_id == project_id,
        )
        result = await db.execute(stmt)
        art = result.scalar_one_or_none()
        if art is None:
            return None

        lineage_ctx = None
        if include_lineage:
            lineage_ctx = await ArtifactIntelligenceService.get_lineage(db, project_id, artifact_id)

        return RetrievalRanker.score_artifact(
            artifact=art, text_score=None, lineage_context=lineage_ctx
        )
