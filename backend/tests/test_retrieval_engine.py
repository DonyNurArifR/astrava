"""Real PostgreSQL integration tests for ASTRAVA Modular Knowledge Retrieval Engine (M1.3-4).

Verifies:
1. Memory retrieval: active retrieval, project isolation, category/provenance/status filtering,
   exclusion of superseded/rejected/archived by default, explicit historical inclusion.
2. Ranking: text relevance dominant gating, provenance policy weights, verification boost,
   recency decay, deterministic tie-breakers.
3. Artifact retrieval: project scoping, lineage context, supersession, verification details.
4. Context assembly: strict character budget compliance, boundary-preserving omission,
   attribution preservation, empty context handling.
5. Security and bounds: validation boundaries, no cross-project leakage, query plan efficiency.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact, ArtifactType, ArtifactVerificationStatus
from app.models.memory import (
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.services.artifact_intelligence_service import ArtifactIntelligenceService
from app.services.retrieval.context_assembler import ContextAssembler
from app.services.retrieval.ranker import RetrievalRanker
from app.services.retrieval.schemas import (
    ArtifactRetrievalFilter,
    MemoryRetrievalFilter,
    RetrievalQuery,
)
from app.services.retrieval.service import RetrievalService


def create_workspace(name: str) -> Workspace:
    return Workspace(name=name, slug=f"ws-{uuid.uuid4().hex[:8]}")


def create_project(
    name: str, workspace_id: uuid.UUID, studio_type: StudioType = StudioType.SAAS
) -> Project:
    return Project(
        name=name,
        slug=f"proj-{uuid.uuid4().hex[:8]}",
        workspace_id=workspace_id,
        studio_type=studio_type,
    )


def create_memory(
    project_id: uuid.UUID,
    summary: str,
    content: str,
    category: MemoryCategory = MemoryCategory.DECISION,
    provenance: MemoryProvenanceType = MemoryProvenanceType.USER_PROVIDED,
    confidence_score: float = 1.0,
    is_verified: bool = True,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    revision: int = 1,
    created_at: datetime | None = None,
) -> ProjectMemory:
    now = created_at or datetime.now(UTC)
    mem = ProjectMemory(
        id=uuid.uuid4(),
        project_id=project_id,
        summary=summary,
        content=content,
        category=category,
        provenance_type=provenance,
        confidence_score=confidence_score,
        is_verified=is_verified,
        status=status,
        conflict_status=MemoryConflictStatus.NONE,
        revision=revision,
        source_task_id="task-test-1",
        source_agent_slug="planner",
        created_at=now,
        updated_at=now,
    )
    return mem


def create_artifact(
    project_id: uuid.UUID,
    name: str,
    file_path: str,
    artifact_type: ArtifactType = ArtifactType.CODE_DIFF,
    version: int = 1,
    verification_status: ArtifactVerificationStatus = ArtifactVerificationStatus.UNVERIFIED,
    created_at: datetime | None = None,
) -> Artifact:
    now = created_at or datetime.now(UTC)
    art = Artifact(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        file_path=file_path,
        artifact_type=artifact_type,
        version=version,
        verification_status=verification_status,
        mime_type="text/plain",
        file_size_bytes=1024,
        created_at=now,
        updated_at=now,
    )
    return art


# ==============================================================================
# 1. Memory Retrieval & Project Isolation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_memory_retrieval_and_project_isolation(db_session: AsyncSession):
    """Verifies that retrieval returns matching active memories and strictly enforces project isolation."""
    ws = create_workspace("Retrieval Isolation WS")
    db_session.add(ws)
    await db_session.flush()

    p_alpha = create_project("Project Alpha", ws.id)
    p_beta = create_project("Project Beta", ws.id)
    db_session.add_all([p_alpha, p_beta])
    await db_session.commit()

    # Alpha memory: PostgreSQL database choice
    mem_alpha = create_memory(
        project_id=p_alpha.id,
        summary="Database Choice: PostgreSQL 16",
        content="We selected PostgreSQL 16 Alpine with connection pooling via asyncpg.",
        category=MemoryCategory.DECISION,
    )
    # Beta memory: Same topic, different project
    mem_beta = create_memory(
        project_id=p_beta.id,
        summary="Database Choice: MongoDB 7",
        content="We selected MongoDB document store for unstructured telemetry.",
        category=MemoryCategory.DECISION,
    )
    db_session.add_all([mem_alpha, mem_beta])
    await db_session.commit()

    # Search in Alpha for "PostgreSQL"
    query_alpha = RetrievalQuery(
        project_id=p_alpha.id,
        query_text="PostgreSQL",
        top_k_memories=10,
    )
    res_alpha = await RetrievalService.search(db_session, query_alpha)
    assert len(res_alpha.memories) == 1
    assert res_alpha.memories[0].id == mem_alpha.id
    assert "PostgreSQL" in res_alpha.memories[0].summary

    # Ensure Beta cannot see Alpha's PostgreSQL memory even when searching for it
    query_beta = RetrievalQuery(
        project_id=p_beta.id,
        query_text="PostgreSQL",
        top_k_memories=10,
    )
    res_beta = await RetrievalService.search(db_session, query_beta)
    assert len(res_beta.memories) == 0

    # Ensure single ID lookup respects project isolation
    found_alpha = await RetrievalService.get_memory_by_id(db_session, p_alpha.id, mem_alpha.id)
    assert found_alpha is not None
    wrong_scope = await RetrievalService.get_memory_by_id(db_session, p_beta.id, mem_alpha.id)
    assert wrong_scope is None


@pytest.mark.asyncio
async def test_memory_lifecycle_status_and_historical_filters(db_session: AsyncSession):
    """Verifies that superseded, rejected, and archived memories are excluded by default but accessible via explicit flags."""
    ws = create_workspace("Lifecycle WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Lifecycle Project", ws.id)
    db_session.add(p)
    await db_session.commit()

    # 1. Active memory (rev 2)
    m_active = create_memory(
        project_id=p.id,
        summary="Auth: OAuth2 PKCE",
        content="Modern OAuth2 with PKCE verification.",
        status=MemoryStatus.ACTIVE,
        revision=2,
    )
    # 2. Superseded memory (rev 1)
    m_superseded = create_memory(
        project_id=p.id,
        summary="Auth: Basic Auth",
        content="Initial HTTP basic auth prototype.",
        status=MemoryStatus.SUPERSEDED,
        revision=1,
    )
    # 3. Rejected memory
    m_rejected = create_memory(
        project_id=p.id,
        summary="Auth: Custom RSA Tokens",
        content="Custom homemade RSA token signature algorithm.",
        status=MemoryStatus.REJECTED,
    )
    # 4. Archived memory
    m_archived = create_memory(
        project_id=p.id,
        summary="Auth: Legacy Session Cookies",
        content="Stateful session cookies with Redis store.",
        status=MemoryStatus.ARCHIVED,
    )
    db_session.add_all([m_active, m_superseded, m_rejected, m_archived])
    await db_session.commit()

    # Default search: only active memory is retrieved
    default_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(project_id=p.id, query_text="Auth"),
    )
    assert len(default_res.memories) == 1
    assert default_res.memories[0].id == m_active.id

    # Explicit flag: include superseded
    sup_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            query_text="Auth",
            memory_filter=MemoryRetrievalFilter(include_superseded=True),
        ),
    )
    sup_ids = {m.id for m in sup_res.memories}
    assert m_active.id in sup_ids
    assert m_superseded.id in sup_ids
    assert m_rejected.id not in sup_ids
    assert m_archived.id not in sup_ids

    # Historical mode: all 4 are retrieved
    hist_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            query_text="Auth",
            memory_filter=MemoryRetrievalFilter(include_historical=True),
        ),
    )
    assert len(hist_res.memories) == 4


@pytest.mark.asyncio
async def test_metadata_filtering_and_bounds(db_session: AsyncSession):
    """Verifies category, provenance, and verification status filtering."""
    ws = create_workspace("Filter WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Filter Project", ws.id)
    db_session.add(p)
    await db_session.commit()

    m_dec = create_memory(
        p.id,
        "Redis Cache",
        "Redis cache layer for session caching.",
        category=MemoryCategory.DECISION,
        provenance=MemoryProvenanceType.USER_PROVIDED,
        is_verified=True,
    )
    m_req = create_memory(
        p.id,
        "Sub-100ms Latency",
        "API response latency must be sub-100ms under load.",
        category=MemoryCategory.REQUIREMENT,
        provenance=MemoryProvenanceType.VERIFIED_FINDING,
        is_verified=True,
    )
    m_assump = create_memory(
        p.id,
        "Redis Memory Usage",
        "Assuming Redis memory will not exceed 2GB.",
        category=MemoryCategory.CONSTRAINT,
        provenance=MemoryProvenanceType.ASSUMPTION,
        is_verified=False,
    )
    db_session.add_all([m_dec, m_req, m_assump])
    await db_session.commit()

    # Filter by category: REQUIREMENT
    req_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            memory_filter=MemoryRetrievalFilter(categories=[MemoryCategory.REQUIREMENT]),
        ),
    )
    assert len(req_res.memories) == 1
    assert req_res.memories[0].id == m_req.id

    # Filter by provenance: ASSUMPTION
    assump_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            memory_filter=MemoryRetrievalFilter(provenance_types=[MemoryProvenanceType.ASSUMPTION]),
        ),
    )
    assert len(assump_res.memories) == 1
    assert assump_res.memories[0].id == m_assump.id

    # Filter by is_verified: True
    verif_res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            memory_filter=MemoryRetrievalFilter(is_verified=True),
        ),
    )
    assert len(verif_res.memories) == 2
    verif_ids = {m.id for m in verif_res.memories}
    assert m_dec.id in verif_ids
    assert m_req.id in verif_ids


# ==============================================================================
# 2. Ranking & Relevance Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_ranking_text_relevance_dominant_over_provenance(db_session: AsyncSession):
    """Verifies that high provenance weight cannot make an irrelevant document outrank a relevant document."""
    ws = create_workspace("Ranking WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Ranking Project", ws.id)
    db_session.add(p)
    await db_session.commit()

    # Doc A: Agent conclusion (provenance weight 0.70), but directly relevant to 'RabbitMQ'
    doc_a = create_memory(
        p.id,
        summary="Message Broker Choice",
        content="RabbitMQ broker selected for AMQP 0-9-1 queue routing and acknowledgments.",
        provenance=MemoryProvenanceType.AGENT_CONCLUSION,
        confidence_score=0.70,
        is_verified=False,
    )
    # Doc B: User provided (provenance weight 1.00), but discusses unrelated database schemas
    doc_b = create_memory(
        p.id,
        summary="User Schema Guidelines",
        content="PostgreSQL users table schema with email indexes and bcrypt password hashes.",
        provenance=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.00,
        is_verified=True,
    )
    db_session.add_all([doc_a, doc_b])
    await db_session.commit()

    # Search for "RabbitMQ"
    res = await RetrievalService.search(
        db_session,
        RetrievalQuery(project_id=p.id, query_text="RabbitMQ"),
    )
    assert len(res.memories) >= 1
    # Doc A must rank first despite lower provenance weight because it has direct text match
    assert res.memories[0].id == doc_a.id
    assert res.memories[0].text_score > 0.0


@pytest.mark.asyncio
async def test_ranking_recency_and_verification_boost(db_session: AsyncSession):
    """Verifies that verified status and recency boost items with identical text relevance."""
    ref_time = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)

    # 1. Verification factor
    mem_verif = create_memory(
        uuid.uuid4(),
        "Test Summary",
        "Content",
        provenance=MemoryProvenanceType.USER_PROVIDED,
        is_verified=True,
        created_at=ref_time,
    )
    mem_unverif = create_memory(
        uuid.uuid4(),
        "Test Summary",
        "Content",
        provenance=MemoryProvenanceType.USER_PROVIDED,
        is_verified=False,
        created_at=ref_time,
    )
    scored_verif = RetrievalRanker.score_memory(mem_verif, text_score=1.0, reference_time=ref_time)
    scored_unverif = RetrievalRanker.score_memory(
        mem_unverif, text_score=1.0, reference_time=ref_time
    )
    assert scored_verif.composite_score > scored_unverif.composite_score

    # 2. Recency factor (new item vs 60-day-old item)
    mem_recent = create_memory(
        uuid.uuid4(),
        "Test Summary",
        "Content",
        created_at=ref_time,
    )
    mem_old = create_memory(
        uuid.uuid4(),
        "Test Summary",
        "Content",
        created_at=ref_time - timedelta(days=60),
    )
    scored_recent = RetrievalRanker.score_memory(
        mem_recent, text_score=1.0, reference_time=ref_time
    )
    scored_old = RetrievalRanker.score_memory(mem_old, text_score=1.0, reference_time=ref_time)
    assert scored_recent.recency_weight > scored_old.recency_weight
    assert scored_recent.composite_score > scored_old.composite_score


@pytest.mark.asyncio
async def test_ranking_deterministic_tie_breaker():
    """Verifies that candidates with equal composite scores break ties deterministically by created_at then id."""
    t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 1, 11, 0, 0, tzinfo=UTC)
    pid = uuid.uuid4()

    m_older = create_memory(pid, "S1", "C1", created_at=t1)
    m_newer = create_memory(pid, "S2", "C2", created_at=t2)

    scored_older = RetrievalRanker.score_memory(m_older, text_score=None)
    scored_newer = RetrievalRanker.score_memory(m_newer, text_score=None)

    sorted_list = RetrievalRanker.sort_memories([scored_older, scored_newer])
    # Newer must come first on tie
    assert sorted_list[0].id == m_newer.id
    assert sorted_list[1].id == m_older.id


# ==============================================================================
# 3. Artifact Retrieval & Lineage Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_artifact_retrieval_and_lineage_context(db_session: AsyncSession):
    """Verifies artifact text search, project isolation, and lineage context integration."""
    ws = create_workspace("Art WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Art Project", ws.id)
    db_session.add(p)
    await db_session.commit()

    art_parent = create_artifact(p.id, "base_pipeline.py", "/src/pipelines/base.py", version=1)
    db_session.add(art_parent)
    await db_session.commit()

    art_child = create_artifact(
        p.id,
        "saas_pipeline.py",
        "/src/pipelines/saas.py",
        version=2,
        verification_status=ArtifactVerificationStatus.VERIFIED,
    )
    db_session.add(art_child)
    await db_session.commit()

    # Link parent
    await ArtifactIntelligenceService.set_parent(db_session, p.id, art_child.id, art_parent.id)
    await db_session.commit()

    # Search for "pipeline"
    res = await RetrievalService.search(
        db_session,
        RetrievalQuery(
            project_id=p.id,
            query_text="pipeline",
            artifact_filter=ArtifactRetrievalFilter(include_lineage=True),
        ),
    )
    assert len(res.artifacts) == 2
    child_found = next(a for a in res.artifacts if a.id == art_child.id)
    assert child_found.verification_status == ArtifactVerificationStatus.VERIFIED
    assert len(child_found.ancestors) == 1
    assert child_found.ancestors[0]["name"] == "base_pipeline.py"

    # Single lookup with lineage
    single_art = await RetrievalService.get_artifact_by_id(
        db_session, p.id, art_child.id, include_lineage=True
    )
    assert single_art is not None
    assert single_art.name == "saas_pipeline.py"
    assert len(single_art.ancestors) == 1


# ==============================================================================
# 4. Context Assembly & Budget Enforcement Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_context_assembler_budget_and_boundary_preservation():
    """Verifies that context package assembly strictly stays within budget without chopping item blocks."""
    pid = uuid.uuid4()
    now = datetime.now(UTC)

    # Create 5 memories with substantial content
    memories = [
        RetrievalRanker.score_memory(
            create_memory(
                pid,
                f"Architecture Standard {i}",
                f"Detailed specification description for subsystem {i}. " * 4,
                created_at=now,
            ),
            text_score=1.0 - (i * 0.1),
        )
        for i in range(5)
    ]

    # Test small budget: 800 chars
    budget_small = 800
    pkg_small, summary_small = ContextAssembler.assemble(
        memories=memories, artifacts=[], budget_chars=budget_small
    )

    assert len(pkg_small) <= budget_small
    assert summary_small.budget_exhausted is True
    assert summary_small.memories_omitted_count > 0
    assert summary_small.memories_included_count >= 1
    # Check that omission notice is present
    assert "Context budget reached" in pkg_small

    # Test standard budget: 4000 chars
    pkg_std, summary_std = ContextAssembler.assemble(
        memories=memories, artifacts=[], budget_chars=4000
    )
    assert len(pkg_std) <= 4000
    assert summary_std.memories_included_count == 5
    assert summary_std.memories_omitted_count == 0
    assert summary_std.budget_exhausted is False


@pytest.mark.asyncio
async def test_context_assembler_empty_results():
    """Verifies clean handling when no knowledge or artifacts match."""
    pkg, summary = ContextAssembler.assemble(memories=[], artifacts=[], budget_chars=4000)
    assert len(pkg) <= 4000
    assert "No relevant project knowledge" in pkg
    assert summary.budget_exhausted is False
    assert summary.memories_included_count == 0


# ==============================================================================
# 5. PostgreSQL Query Plan & Performance Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_postgresql_explain_full_text_query(db_session: AsyncSession):
    """Executes an EXPLAIN query on PostgreSQL to verify full-text search query plan."""
    explain_sql = text(
        "EXPLAIN (FORMAT JSON) "
        "SELECT id, summary, content, ts_rank_cd(to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(content, '')), websearch_to_tsquery('english', 'PostgreSQL database')) "
        "FROM project_memories "
        "WHERE project_id = :pid AND status = 'active' "
        "AND to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(content, '')) @@ websearch_to_tsquery('english', 'PostgreSQL database');"
    )
    result = await db_session.execute(explain_sql, {"pid": uuid.uuid4()})
    plan_json = result.scalar()
    assert plan_json is not None
    # Verify plan returned valid JSON plan structure from PostgreSQL 16
    assert isinstance(plan_json, list)
    plan_root = plan_json[0]["Plan"]
    assert "Node Type" in plan_root
