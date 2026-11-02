"""Database-side memory retriever for ASTRAVA knowledge retrieval.

Executes project-scoped queries against PostgreSQL 16 using full-text search,
GIN indexes, and metadata filters.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import ProjectMemory
from app.services.retrieval.metadata_filter import MetadataFilter
from app.services.retrieval.query_processor import ProcessedQuery, QueryProcessor
from app.services.retrieval.ranker import RetrievalRanker
from app.services.retrieval.schemas import MemoryRetrievalFilter, ScoredMemory

logger = logging.getLogger("astrava.retrieval.memory")


class MemoryRetriever:
    """Retrieves and scores project memories from PostgreSQL."""

    @classmethod
    async def retrieve(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        processed_query: ProcessedQuery,
        filter_spec: MemoryRetrievalFilter | None = None,
        top_k: int = 20,
        min_threshold: float = 0.0,
        reference_time: datetime | None = None,
    ) -> list[ScoredMemory]:
        """Retrieves and ranks ProjectMemory records matching query and filters.

        Always strictly isolates retrieval by project_id.
        """
        base_filters = MetadataFilter.build_memory_filters(project_id, filter_spec)

        if processed_query.is_empty or not processed_query.normalized_text:
            # ------------------------------------------------------------------
            # Empty Query Path: Metadata-only retrieval ordered by recency
            # ------------------------------------------------------------------
            stmt = (
                select(ProjectMemory)
                .where(and_(*base_filters))
                .order_by(ProjectMemory.created_at.desc(), ProjectMemory.id.asc())
                .limit(min(top_k * 2, 100))
            )
            result = await db.execute(stmt)
            rows = list(result.scalars().all())

            scored = [
                RetrievalRanker.score_memory(
                    memory=row, text_score=None, reference_time=reference_time
                )
                for row in rows
            ]
            filtered = [s for s in scored if s.composite_score >= min_threshold]
            return RetrievalRanker.sort_memories(filtered)[:top_k]

        # ------------------------------------------------------------------
        # Full-Text Search Path: PostgreSQL tsvector & ts_rank_cd
        # ------------------------------------------------------------------
        clean_text = processed_query.normalized_text
        tsv_expr = func.to_tsvector(
            "english",
            func.coalesce(ProjectMemory.summary, "")
            + " "
            + func.coalesce(ProjectMemory.content, ""),
        )
        tsquery_and_expr = func.websearch_to_tsquery("english", clean_text)

        # Match either exact tsquery or OR-based tsquery across significant tokens
        text_matches: list[Any] = [tsv_expr.op("@@")(tsquery_and_expr)]
        or_query_terms = QueryProcessor.build_or_tsquery_terms(processed_query)
        if or_query_terms:
            tsquery_or_expr = func.websearch_to_tsquery("english", or_query_terms)
            text_matches.append(tsv_expr.op("@@")(tsquery_or_expr))
            rank_expr = func.ts_rank_cd(tsv_expr, tsquery_or_expr)
        else:
            rank_expr = func.ts_rank_cd(tsv_expr, tsquery_and_expr)

        # Match case-insensitive keyword substrings for significant tokens
        sig_tokens = [t for t in processed_query.tokens if len(t) >= 3]
        for token in sig_tokens[:5]:
            text_matches.append(ProjectMemory.summary.ilike(f"%{token}%"))
            text_matches.append(ProjectMemory.content.ilike(f"%{token}%"))

        combined_filter = and_(*base_filters, or_(*text_matches))

        stmt = (
            select(ProjectMemory, rank_expr.label("raw_rank"))
            .where(combined_filter)
            .order_by(rank_expr.desc(), ProjectMemory.created_at.desc())
            .limit(min(top_k * 3, 150))
        )

        result = await db.execute(stmt)
        candidate_rows = result.all()

        scored_candidates: list[ScoredMemory] = []
        for mem, raw_rank in candidate_rows:
            # Normalize PostgreSQL ts_rank_cd (which typically ranges [0.01, 0.5])
            # into a [0.1, 1.0] scale; if matched via ILIKE with 0 rank, assign base 0.50
            if raw_rank and raw_rank > 0.0:
                # Sigmoidal/bounded scaling: 0.1 rank yields ~0.67, 0.2 rank yields ~0.83
                normalized_rank = min(1.0, float(raw_rank) * 8.0)
            else:
                normalized_rank = 0.50

            scored_item = RetrievalRanker.score_memory(
                memory=mem,
                text_score=normalized_rank,
                reference_time=reference_time,
            )
            if scored_item.composite_score >= min_threshold:
                scored_candidates.append(scored_item)

        sorted_results = RetrievalRanker.sort_memories(scored_candidates)
        return sorted_results[:top_k]
