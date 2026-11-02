"""Database-side artifact retriever for ASTRAVA knowledge retrieval.

Executes project-scoped queries against PostgreSQL 16 using full-text search,
GIN indexes, and lineage graph traversal via ArtifactIntelligenceService.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.services.artifact_intelligence_service import ArtifactIntelligenceService
from app.services.retrieval.metadata_filter import MetadataFilter
from app.services.retrieval.query_processor import ProcessedQuery, QueryProcessor
from app.services.retrieval.ranker import RetrievalRanker
from app.services.retrieval.schemas import ArtifactRetrievalFilter, ScoredArtifact

logger = logging.getLogger("astrava.retrieval.artifact")


class ArtifactRetriever:
    """Retrieves and scores project artifacts from PostgreSQL."""

    @classmethod
    async def retrieve(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        processed_query: ProcessedQuery,
        filter_spec: ArtifactRetrievalFilter | None = None,
        top_k: int = 10,
        min_threshold: float = 0.0,
        reference_time: datetime | None = None,
    ) -> list[ScoredArtifact]:
        """Retrieves and ranks Artifact records matching query and filters.

        Always strictly isolates retrieval by project_id.
        """
        if top_k <= 0:
            return []

        base_filters = MetadataFilter.build_artifact_filters(project_id, filter_spec)
        include_lineage = filter_spec.include_lineage if filter_spec else True

        if processed_query.is_empty or not processed_query.normalized_text:
            # Empty query path
            stmt = (
                select(Artifact)
                .where(and_(*base_filters))
                .order_by(Artifact.created_at.desc(), Artifact.id.asc())
                .limit(min(top_k * 2, 50))
            )
            result = await db.execute(stmt)
            artifacts = list(result.scalars().all())

            scored: list[ScoredArtifact] = []
            for art in artifacts:
                lineage_ctx = None
                if include_lineage:
                    try:
                        lineage_ctx = await ArtifactIntelligenceService.get_lineage(
                            db, project_id, art.id
                        )
                    except Exception as e:
                        logger.warning("Failed to get lineage for artifact %s: %s", art.id, e)

                scored_item = RetrievalRanker.score_artifact(
                    artifact=art,
                    text_score=None,
                    lineage_context=lineage_ctx,
                    reference_time=reference_time,
                )
                if scored_item.composite_score >= min_threshold:
                    scored.append(scored_item)

            return RetrievalRanker.sort_artifacts(scored)[:top_k]

        # Full-text search path
        clean_text = processed_query.normalized_text
        tsv_expr = func.to_tsvector(
            "english",
            func.coalesce(Artifact.name, "") + " " + func.coalesce(Artifact.file_path, ""),
        )
        tsquery_and_expr = func.websearch_to_tsquery("english", clean_text)

        text_matches: list[Any] = [tsv_expr.op("@@")(tsquery_and_expr)]
        or_query_terms = QueryProcessor.build_or_tsquery_terms(processed_query)
        if or_query_terms:
            tsquery_or_expr = func.websearch_to_tsquery("english", or_query_terms)
            text_matches.append(tsv_expr.op("@@")(tsquery_or_expr))
            rank_expr = func.ts_rank_cd(tsv_expr, tsquery_or_expr)
        else:
            rank_expr = func.ts_rank_cd(tsv_expr, tsquery_and_expr)

        sig_tokens = [t for t in processed_query.tokens if len(t) >= 3]
        for token in sig_tokens[:5]:
            text_matches.append(Artifact.name.ilike(f"%{token}%"))
            text_matches.append(Artifact.file_path.ilike(f"%{token}%"))

        stmt = (
            select(Artifact, rank_expr.label("raw_rank"))
            .where(and_(*base_filters, or_(*text_matches)))
            .order_by(rank_expr.desc(), Artifact.created_at.desc())
            .limit(min(top_k * 3, 100))
        )

        result = await db.execute(stmt)
        candidates = result.all()

        scored_candidates: list[ScoredArtifact] = []
        for art, raw_rank in candidates:
            if raw_rank and raw_rank > 0.0:
                normalized_rank = min(1.0, float(raw_rank) * 8.0)
            else:
                normalized_rank = 0.50

            lineage_ctx = None
            if include_lineage:
                try:
                    lineage_ctx = await ArtifactIntelligenceService.get_lineage(
                        db, project_id, art.id
                    )
                except Exception as e:
                    logger.warning("Failed to get lineage for artifact %s: %s", art.id, e)

            scored_item = RetrievalRanker.score_artifact(
                artifact=art,
                text_score=normalized_rank,
                lineage_context=lineage_ctx,
                reference_time=reference_time,
            )
            if scored_item.composite_score >= min_threshold:
                scored_candidates.append(scored_item)

        sorted_results = RetrievalRanker.sort_artifacts(scored_candidates)
        return sorted_results[:top_k]
