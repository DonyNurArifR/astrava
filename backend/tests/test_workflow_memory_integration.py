"""Real PostgreSQL integration tests for LangGraph Workflow Memory Integration (M1.3-5).

Verifies:
1. Pre-planning knowledge retrieval:
   - Retrieval occurs before planning.
   - Active project memories and constraints reach the planner and downstream agents.
   - Context budget remains strictly enforced.
   - Fallback behavior on empty retrieval or retrieval errors.
2. Post-execution knowledge extraction & ingestion:
   - Durable knowledge (milestone, decisions) extracted from completed tasks.
   - Strict provenance classification: QA-verified findings vs. agent conclusions.
   - Successful execution persists memories and audit logs to PostgreSQL.
   - Failed executions bypass knowledge ingestion.
3. Idempotency, checkpointing, and recovery:
   - Idempotent ingestion: rerunning ingestion does not duplicate memories or audit records.
   - Simulated crash recovery: pre-persisted memories are detected by source_execution_id.
   - Human approval pause and resume preserves memory retrieval context.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalStatus
from app.models.execution import ExecutionStatus
from app.models.memory import (
    MemoryAuditAction,
    MemoryAuditLog,
    MemoryCategory,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.knowledge_extraction import KnowledgeExtractor
from app.orchestrator.runner import OrchestrationRunner
from app.orchestrator.state import OrchestrationState
from app.orchestrator.workflow_graph import (
    ingest_knowledge_node,
    retrieve_knowledge_node,
)
from app.providers.base import ProviderResponse, ProviderStatus
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.memory_service import MemoryService
from app.services.workflow_service import WorkflowService


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


# ==============================================================================
# 1. Pre-Planning Retrieval Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_pre_planning_retrieval_node_populates_state(db_session: AsyncSession):
    """Verifies that retrieve_knowledge_node queries PostgreSQL and populates context in state."""
    ws = create_workspace("Retrieval Graph WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Memory Integrated Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Seed an active architectural decision
    await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Message Broker: RabbitMQ",
        content="RabbitMQ selected for AMQP 0-9-1 queue routing and acknowledgments.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # Initial state before planning
    state: OrchestrationState = {
        "project_id": str(project.id),
        "objective": "Build event-driven microservice using RabbitMQ",
        "studio_type": "saas",
    }

    output = await retrieve_knowledge_node(state)

    assert "retrieved_memories" in output
    assert len(output["retrieved_memories"]) >= 1
    assert "RabbitMQ" in output["retrieval_context"]
    assert output["retrieval_metadata"]["budget_limit_chars"] == 4000
    assert output["retrieval_error"] is None


@pytest.mark.asyncio
async def test_retrieval_node_handles_non_uuid_and_errors_gracefully():
    """Verifies that non-UUID project IDs and retrieval glitches do not fail the workflow."""
    state_mock: OrchestrationState = {
        "project_id": "test-mock-proj",
        "objective": "Test objective",
        "studio_type": "saas",
    }
    output = await retrieve_knowledge_node(state_mock)
    assert output["retrieval_metadata"]["skipped"] is True
    assert output["retrieval_error"] is None
    assert output["retrieved_memories"] == []

    # Test error recovery
    with patch(
        "app.services.retrieval.service.RetrievalService.search",
        side_effect=RuntimeError("Database connection lost"),
    ):
        state_err: OrchestrationState = {
            "project_id": str(uuid.uuid4()),
            "objective": "Test objective",
            "studio_type": "saas",
        }
        err_output = await retrieve_knowledge_node(state_err)
        assert err_output["retrieved_memories"] == []
        assert "Database connection lost" in (err_output["retrieval_error"] or "")
        assert err_output["retrieval_metadata"]["skipped"] is True


@pytest.mark.asyncio
async def test_retrieval_context_integrated_into_planner_and_agent_prompt(
    db_session: AsyncSession,
):
    """Verifies that retrieved memory context flows into the generated plan and downstream agent prompts."""
    ws = create_workspace("Planner Integration WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Planner Context Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Seed an active constraint
    await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.CONSTRAINT,
        summary="Strict Compliance: HIPAA Data Isolation",
        content="All tenant patient records must be encrypted using AES-256 with tenant-scoped keys.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # Execute full pipeline through OrchestrationRunner with mock provider
    mock_output = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="# Architecture Spec\nEnforces HIPAA compliant encryption.\n",
        exit_code=0,
        duration_ms=1500,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = mock_output
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project.id,
            objective="Architect patient record portal",
            studio_type="saas",
        )

    assert execution.status == ExecutionStatus.COMPLETED
    state = execution.state_data or {}
    assert "retrieval_context" in state
    assert "HIPAA" in state["retrieval_context"]

    # Verify agent prompt received the persistent memory context
    prompt_sent = mock_exec.call_args[0][0].prompt
    assert "Persistent Memory" in prompt_sent
    assert "HIPAA" in prompt_sent


# ==============================================================================
# 2. Post-Execution Knowledge Ingestion Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_successful_execution_ingests_memories_and_audits(
    db_session: AsyncSession,
):
    """Verifies that completing an execution ingests durable knowledge and appends audit logs."""
    ws = create_workspace("Ingest WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Ingest Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mock_resp = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="# System Design\nSelected PostgreSQL 16 with pgvector for hybrid retrieval.\n",
        exit_code=0,
        duration_ms=1200,
        input_tokens=80,
        output_tokens=40,
        cost_usd=0.001,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = mock_resp
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project.id,
            objective="Build hybrid search microservice",
            studio_type="saas",
        )

    assert execution.status == ExecutionStatus.COMPLETED
    state = execution.state_data or {}
    assert state.get("ingestion_status") == "completed"
    ingested_ids = state.get("ingested_memory_ids", [])
    assert len(ingested_ids) >= 1

    # Verify rows persisted in PostgreSQL project_memories
    mem_stmt = select(ProjectMemory).where(ProjectMemory.project_id == project.id)
    memories = list((await db_session.execute(mem_stmt)).scalars().all())
    assert len(memories) >= 1

    # Check milestone and provenance
    milestone_mem = next((m for m in memories if m.category == MemoryCategory.MILESTONE), None)
    assert milestone_mem is not None
    assert milestone_mem.source_execution_id == execution.id
    assert milestone_mem.status == MemoryStatus.ACTIVE

    # Check that audit log entries were recorded
    audit_stmt = select(MemoryAuditLog).where(
        MemoryAuditLog.project_id == project.id,
        MemoryAuditLog.action == MemoryAuditAction.CREATED,
    )
    audit_logs = list((await db_session.execute(audit_stmt)).scalars().all())
    assert len(audit_logs) >= len(memories)


@pytest.mark.asyncio
async def test_provenance_classification_rules(db_session: AsyncSession):
    """Verifies that QA-verified tasks yield verified_finding while standard agent outputs yield agent_conclusion."""
    exec_id = str(uuid.uuid4())
    proj_id = str(uuid.uuid4())

    # State with 1 unverified strategic task and 1 verified QA task
    state: OrchestrationState = {
        "execution_id": exec_id,
        "project_id": proj_id,
        "objective": "Build secure payment gateway",
        "tasks": [
            {
                "task_id": "task-arch",
                "title": "Conduct Architecture & System Design",
                "assigned_agent_slug": "solution-architect",
                "output_text": "Chose Stripe Elements with webhooks for billing.",
                "status": "completed",
            },
        ],
        "completed_task_ids": ["task-arch"],
        "verification_results": [
            {
                "task_id": "task-arch",
                "report": {"overall_passed": False},  # No programmatic test suite
            }
        ],
        "artifacts": [],
    }

    candidates = KnowledgeExtractor.extract_from_execution(state)
    arch_cand = next(c for c in candidates if c.source_task_id == "task-arch")
    assert arch_cand.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION
    assert arch_cand.is_verified is False
    assert arch_cand.confidence_score == 0.70

    # Now simulate verified QA execution
    state_verified: OrchestrationState = dict(state)
    state_verified["verification_results"] = [
        {
            "task_id": "task-arch",
            "report": {"overall_passed": True},  # Automated verification passed
        }
    ]
    candidates_verif = KnowledgeExtractor.extract_from_execution(state_verified)
    arch_cand_verif = next(c for c in candidates_verif if c.source_task_id == "task-arch")
    assert arch_cand_verif.provenance_type == MemoryProvenanceType.VERIFIED_FINDING
    assert arch_cand_verif.is_verified is True
    assert arch_cand_verif.confidence_score == 0.95


@pytest.mark.asyncio
async def test_failed_execution_bypasses_knowledge_ingestion(db_session: AsyncSession):
    """Verifies that a failed execution never reaches the knowledge ingestion node."""
    ws = create_workspace("Failed Exec WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Failed Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Simulate provider failure on all attempts
    mock_fail = ProviderResponse(
        status=ProviderStatus.FAILED,
        output_text="",
        error_message="Simulated process timeout",
        exit_code=1,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = mock_fail
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project.id,
            objective="Will fail execution",
            studio_type="saas",
        )

    assert execution.status == ExecutionStatus.FAILED
    state = execution.state_data or {}
    # Ingestion status must not be completed
    assert state.get("ingestion_status") != "completed"
    assert not state.get("ingested_memory_ids")

    # Confirm zero memories were persisted for this execution
    stmt = select(ProjectMemory).where(ProjectMemory.source_execution_id == execution.id)
    records = list((await db_session.execute(stmt)).scalars().all())
    assert len(records) == 0


# ==============================================================================
# 3. Idempotency & Crash Recovery Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_ingest_knowledge_idempotency_on_retry(db_session: AsyncSession):
    """Verifies that running ingest_knowledge_node multiple times produces zero duplicate memories."""
    ws = create_workspace("Idempotency WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Idempotency Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    wf = await WorkflowService.create_workflow(
        db_session,
        WorkflowCreate(
            project_id=project.id,
            name="Idempotency Test WF",
            studio_type="saas",
        ),
    )
    exec_row = await WorkflowService.create_execution(
        db_session,
        ExecutionCreate(
            workflow_id=wf.id,
            project_id=project.id,
        ),
    )
    await db_session.commit()
    exec_id = exec_row.id
    state: OrchestrationState = {
        "execution_id": str(exec_id),
        "project_id": str(project.id),
        "objective": "Build idempotent payment worker",
        "tasks": [
            {
                "task_id": "task-arch",
                "title": "Conduct Architecture & System Design",
                "assigned_agent_slug": "solution-architect",
                "output_text": "Idempotent event processing via Redis dedup keys.",
                "status": "completed",
            }
        ],
        "completed_task_ids": ["task-arch"],
        "verification_results": [],
        "artifacts": [],
    }

    # First run
    res_1 = await ingest_knowledge_node(state)
    assert res_1["ingestion_status"] == "completed"
    initial_ids = res_1["ingested_memory_ids"]
    assert len(initial_ids) >= 1

    # Count records in database
    count_stmt = select(ProjectMemory).where(ProjectMemory.source_execution_id == exec_id)
    count_1 = len(list((await db_session.execute(count_stmt)).scalars().all()))
    assert count_1 == len(initial_ids)

    # Second run with in-memory state updated
    state.update(res_1)
    res_2 = await ingest_knowledge_node(state)
    # Returns immediately without DB operations
    assert res_2 == {}

    # Third run simulating a crash before checkpoint persistence:
    # in-memory state does NOT have ingestion_status, but database has the records
    state_crashed: OrchestrationState = {
        "execution_id": str(exec_id),
        "project_id": str(project.id),
        "objective": "Build idempotent payment worker",
        "tasks": state["tasks"],
        "completed_task_ids": ["task-arch"],
        "verification_results": [],
        "artifacts": [],
    }
    res_3 = await ingest_knowledge_node(state_crashed)
    assert res_3["ingestion_status"] == "completed"
    # Returns the existing IDs from DB
    assert set(res_3["ingested_memory_ids"]) == set(initial_ids)

    # Verify zero duplicate rows created in PostgreSQL
    count_3 = len(list((await db_session.execute(count_stmt)).scalars().all()))
    assert count_3 == count_1


@pytest.mark.asyncio
async def test_approval_interruption_and_resume_preserves_retrieval(
    db_session: AsyncSession,
):
    """Verifies that pausing for approval and resuming preserves pre-planning retrieval context."""
    ws = create_workspace("Resume WS")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Resume Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Pre-seed memory
    await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Video Codec: H.265 / AV1",
        content="Target export codec is AV1 with H.265 fallback.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    mock_resp = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="Deliverable content meeting approval criteria.\n",
        exit_code=0,
        duration_ms=1000,
        input_tokens=50,
        output_tokens=25,
        cost_usd=0.0005,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = mock_resp
        # Media Studio pipeline includes approval requirement on final quality review
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project.id,
            objective="Produce video documentary episode using AV1 codec",
            studio_type="media",
        )

        assert execution.status == ExecutionStatus.WAITING_APPROVAL
        pre_state = execution.state_data or {}
        assert "retrieval_context" in pre_state
        assert "AV1" in pre_state["retrieval_context"]

        # Resume pipeline with operator approval
        resumed = await OrchestrationRunner.resume_pipeline(
            db=db_session,
            execution_id=execution.id,
            decision_req=ApprovalDecisionRequest(
                decision=ApprovalStatus.APPROVED,
                reason="Video quality standards approved",
                decided_by="operator-1",
            ),
        )

        assert resumed.status == ExecutionStatus.COMPLETED
        post_state = resumed.state_data or {}
        # Retrieval context was preserved across resume
        assert "retrieval_context" in post_state
        assert "AV1" in post_state["retrieval_context"]
        assert post_state.get("ingestion_status") == "completed"
