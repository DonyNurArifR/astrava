"""End-to-End Cross-Execution Project Intelligence Acceptance Test (Phase C / M1.3-8).

Demonstrates persistent project intelligence across three separate, connected executions:
- Execution A: Establishes durable project knowledge, requirements, architectural decisions, and artifact lineage.
- Execution B: Reuses persistent project knowledge; pre-planning retrieval populates context budget and guides planning.
- Execution C: Evolves and challenges knowledge; introduces conflicting decision, detects conflict, and resolves it cleanly.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact, ArtifactType
from app.models.execution import ExecutionStatus
from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.models.project import Project
from app.models.workspace import Workspace
from app.orchestrator.runner import OrchestrationRunner
from app.providers.base import ProviderResponse, ProviderStatus
from app.services.artifact_intelligence_service import ArtifactIntelligenceService
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_service import MemoryService
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.service import RetrievalService


@pytest.fixture
async def cross_exec_project(db_session: AsyncSession):
    ws = Workspace(name="Invoice Intelligence WS", slug=f"inv-ws-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()

    proj = Project(
        name="Autonomous Invoice & Fraud Audit Platform",
        slug=f"invoice-platform-{uuid.uuid4().hex[:8]}",
        workspace_id=ws.id,
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest.fixture
async def isolated_project(db_session: AsyncSession):
    ws = Workspace(name="Isolated WS", slug=f"iso-ws-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()

    proj = Project(
        name="Isolated Unrelated Platform",
        slug=f"iso-proj-{uuid.uuid4().hex[:8]}",
        workspace_id=ws.id,
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest.mark.asyncio
async def test_full_cross_execution_project_intelligence_lifecycle(
    db_session: AsyncSession,
    cross_exec_project: Project,
    isolated_project: Project,
):
    project_id = cross_exec_project.id

    # ==================================================================
    # EXECUTION A — Establish Initial Project Knowledge
    # ==================================================================
    obj_a = "Build an autonomous invoice validation and fraud audit platform with webhook notifications."

    mock_resp_a = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text=(
            "# Architecture Decision: Storage & Vector Search\n"
            "Selected PostgreSQL 16 with pgvector extension for ACID transactions and native vector indexing.\n"
            "Webhook authentication mandates HMAC-SHA256 request signatures with rotating secrets.\n"
        ),
        exit_code=0,
        duration_ms=1500,
        input_tokens=250,
        output_tokens=120,
        cost_usd=0.002,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
    ) as mock_cli:
        mock_cli.return_value = mock_resp_a
        exec_a = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project_id,
            objective=obj_a,
            studio_type="saas",
        )

    assert exec_a.status == ExecutionStatus.COMPLETED
    state_a = exec_a.state_data or {}
    assert state_a.get("ingestion_status") == "completed"

    # Verify memories in PostgreSQL for Execution A
    mems_a_stmt = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
    mems_a = list((await db_session.execute(mems_a_stmt)).scalars().all())
    assert len(mems_a) >= 2, "Expected at least milestone and architectural decision memories"

    # Inspect decision memory
    decision_mem = next(
        (
            m
            for m in mems_a
            if "Architecture Decision" in m.summary or m.category == MemoryCategory.DECISION
        ),
        None,
    )
    assert decision_mem is not None
    assert decision_mem.source_execution_id == exec_a.id
    assert decision_mem.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION
    assert decision_mem.is_verified is False

    # Create an initial artifact with lineage for Execution A
    art_v1 = Artifact(
        project_id=project_id,
        name="invoice_spec_v1.md",
        file_path="specs/invoice_spec_v1.md",
        artifact_type=ArtifactType.ARCHITECTURE,
        file_size_bytes=4096,
        version=1,
        verification_status="unverified",
    )
    db_session.add(art_v1)
    await db_session.commit()
    await db_session.refresh(art_v1)

    # Operator explicitly verifies the core architectural decision
    verified_decision = await MemoryService.verify_memory(
        db=db_session,
        project_id=project_id,
        memory_id=decision_mem.id,
        verified_by="Lead-Architect",
        verification_details={"review_board": "Architecture Council", "approved": True},
        actor_type="user",
        actor_id="Lead-Architect",
        reason="Ratified PostgreSQL 16 + pgvector and HMAC-SHA256 signature architecture.",
    )
    await db_session.commit()
    assert verified_decision.is_verified is True
    assert verified_decision.provenance_type == MemoryProvenanceType.VERIFIED_FINDING
    assert verified_decision.status == MemoryStatus.ACTIVE

    # ==================================================================
    # EXECUTION B — Reuse Persistent Knowledge Before Planning
    # ==================================================================
    obj_b = "Design the authentication and webhook subsystem for the invoice validation platform respecting established architecture."

    # 1. Verify retrieval service behavior directly for Execution B's query
    retrieval_query = RetrievalQuery(
        project_id=project_id,
        query_text="webhook authentication and postgresql vector database",
        top_k_memories=5,
    )
    retrieval_res = await RetrievalService.search(
        db=db_session,
        query=retrieval_query,
    )
    assert len(retrieval_res.memories) >= 1
    # Check that the verified decision memory was retrieved and ranked
    retrieved_ids = [str(m.id) for m in retrieval_res.memories]
    assert str(decision_mem.id) in retrieved_ids

    # 2. Check assembled context contains structured citations
    context_str = retrieval_res.context_package
    assert "pgvector" in context_str or "PostgreSQL" in context_str
    assert "verified_finding" in context_str
    assert "solution-architect" in context_str

    # 3. Verify Project Isolation: Unrelated project retrieves NOTHING from Execution A
    iso_query = RetrievalQuery(
        project_id=isolated_project.id,
        query_text="webhook authentication and postgresql vector database",
        top_k_memories=5,
    )
    iso_res = await RetrievalService.search(
        db=db_session,
        query=iso_query,
    )
    assert len(iso_res.memories) == 0, "Unrelated project must not retrieve Execution A memories"
    assert "No relevant project knowledge" in iso_res.context_package

    # 4. Run Execution B pipeline through LangGraph
    mock_resp_b = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text=(
            "# Webhook Security Implementation\n"
            "Implemented HMAC-SHA256 verification middleware following project architecture decision.\n"
            "Integrated with PostgreSQL pgvector audit table for request tracing.\n"
        ),
        exit_code=0,
        duration_ms=1200,
        input_tokens=300,
        output_tokens=150,
        cost_usd=0.002,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
    ) as mock_cli:
        mock_cli.return_value = mock_resp_b
        exec_b = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project_id,
            objective=obj_b,
            studio_type="saas",
        )

    assert exec_b.status == ExecutionStatus.COMPLETED
    state_b = exec_b.state_data or {}
    assert state_b.get("ingestion_status") == "completed"

    # Verify that retrieval_context in Execution B state was populated
    retrieved_ctx_b = state_b.get("retrieval_context", "")
    assert len(retrieved_ctx_b) > 0, (
        "Execution B must have populated retrieval_context from Execution A knowledge"
    )
    assert "pgvector" in retrieved_ctx_b or "PostgreSQL" in retrieved_ctx_b

    # Create derived artifact v2 linked to artifact v1
    art_v2 = Artifact(
        project_id=project_id,
        name="invoice_spec_v2.md",
        file_path="specs/invoice_spec_v2.md",
        artifact_type=ArtifactType.ARCHITECTURE,
        file_size_bytes=5120,
        version=2,
        parent_artifact_id=art_v1.id,
        verification_status="unverified",
    )
    db_session.add(art_v2)
    await db_session.commit()
    await db_session.refresh(art_v2)

    await ArtifactIntelligenceService.set_superseded_by(
        db=db_session,
        project_id=project_id,
        artifact_id=art_v1.id,
        superseded_by_id=art_v2.id,
    )
    await db_session.commit()
    await db_session.refresh(art_v1)

    assert art_v2.version == 2
    assert art_v2.parent_artifact_id == art_v1.id
    assert art_v1.superseded_by_id == art_v2.id

    # Verify lineage
    lineage = await ArtifactIntelligenceService.get_lineage(
        db=db_session, project_id=project_id, artifact_id=art_v2.id
    )
    assert len(lineage["ancestors"]) == 1
    assert lineage["ancestors"][0].id == art_v1.id

    # ==================================================================
    # EXECUTION C — Evolve & Challenge Knowledge (Conflict Lifecycle)
    # ==================================================================
    # Introduce a conflicting proposal under the same summary
    conflicting_summary = verified_decision.summary

    # Create competing memory
    competing_mem = await MemoryService.create_memory(
        db=db_session,
        project_id=project_id,
        category=MemoryCategory.DECISION,
        summary=conflicting_summary,
        content="Replace HMAC-SHA256 with mutual TLS (mTLS) client certificate verification for webhooks.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        reason="Security audit proposal",
    )
    await db_session.commit()

    # Verify conflict detected
    reloaded_decision = await MemoryService.get_memory(db_session, project_id, verified_decision.id)
    assert reloaded_decision.conflict_status == MemoryConflictStatus.DETECTED
    assert competing_mem.conflict_status == MemoryConflictStatus.DETECTED
    assert reloaded_decision.conflicting_memory_id == competing_mem.id
    assert competing_mem.conflicting_memory_id == reloaded_decision.id

    # Resolve conflict via MERGE into a unified policy
    merged = await MemoryService.resolve_conflict(
        db=db_session,
        project_id=project_id,
        memory_id=reloaded_decision.id,
        resolution="merge",
        actor_id="Security-Architect",
        reason="Adopt dual-layer authentication: mTLS at gateway with HMAC-SHA256 payload signature.",
        merged_summary=conflicting_summary,
        merged_content="Dual-layer webhook security: TLS 1.3 mTLS mutual authentication combined with HMAC-SHA256 payload verification.",
    )
    await db_session.commit()

    assert merged.status == MemoryStatus.ACTIVE
    assert merged.conflict_status == MemoryConflictStatus.RESOLVED
    assert "Dual-layer webhook security" in merged.content

    # Confirm audit logs record full history
    audit_logs, total_audits = await MemoryAuditService.list_by_memory_paginated(
        db=db_session,
        memory_id=merged.id,
        project_id=project_id,
    )
    assert total_audits >= 1
    actions = [entry.action for entry in audit_logs]
    assert MemoryAuditAction.CONFLICT_RESOLVED in actions or MemoryAuditAction.CREATED in actions
