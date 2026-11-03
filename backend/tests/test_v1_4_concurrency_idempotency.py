"""V1.4 M1.4-1 (Phase D): Real PostgreSQL concurrency and idempotency tests.

Runs ``ingest_knowledge_node`` against the real PostgreSQL database (no mocks of the
persistence layer) to verify:

1. First ingestion persists memories, fingerprints, and CREATED audit rows.
2. Exact retry with the same operation token creates no duplicates.
3. A new batch in the same execution (new operation token) persists legitimate new
   knowledge instead of being suppressed.
4. Ten concurrent requests for the same operation create zero duplicates.
5. Concurrent distinct operations do not suppress or drop each other's memories.
6. A candidate failure midway is isolated by its savepoint and captured.
7. A failed operation can be corrected and retried successfully.
8. Revision history and audit trail stay intact for ingested memories.
9. Conflict detection still fires for ingested memories with competing content.
10. Projects are isolated: identical candidate data yields separate, valid memories.
11. The partial unique index on (project_id, fingerprint) is enforced by PostgreSQL.
"""

import asyncio
import copy
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.execution import WorkflowExecution
from app.models.memory import (
    IngestionOperation,
    IngestionOperationStatus,
    MemoryAuditAction,
    MemoryAuditLog,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.state import OrchestrationState
from app.orchestrator.workflow_graph import ingest_knowledge_node
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.memory_service import MemoryService
from app.services.workflow_service import WorkflowService

ARCH_TITLE = "Conduct Architecture & System Design"
ARCH_OUTPUT = "Use idempotent event processing with Redis-backed dedup keys per task."
OBJECTIVE = "Build idempotent payment worker"


# ==============================================================================
# Helpers
# ==============================================================================


async def _seed_project_and_execution(
    db: AsyncSession, label: str
) -> tuple[Project, WorkflowExecution]:
    ws = Workspace(name=f"{label} WS", slug=f"ws-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()

    project = Project(
        name=f"{label} Project",
        slug=f"proj-{uuid.uuid4().hex[:8]}",
        workspace_id=ws.id,
        studio_type=StudioType.SAAS,
    )
    db.add(project)
    await db.commit()

    wf = await WorkflowService.create_workflow(
        db,
        WorkflowCreate(project_id=project.id, name=f"{label} WF", studio_type="saas"),
    )
    exec_row = await WorkflowService.create_execution(
        db, ExecutionCreate(workflow_id=wf.id, project_id=project.id)
    )
    await db.commit()
    return project, exec_row


def _arch_task(task_id: str = "task-arch") -> dict:
    return {
        "task_id": task_id,
        "title": ARCH_TITLE,
        "assigned_agent_slug": "solution-architect",
        "output_text": ARCH_OUTPUT,
        "status": "completed",
    }


def _backend_task(index: int = 6) -> dict:
    return {
        "task_id": f"task-{index}-backend",
        "title": f"Backend System Design for Task {index}",
        "assigned_agent_slug": "lead-developer",
        "output_text": f"Backend task {index} persists payment events in Postgres.",
        "status": "completed",
    }


def _build_state(
    project: Project,
    exec_id: uuid.UUID,
    operation_token: str,
    tasks: list[dict],
    objective: str = OBJECTIVE,
) -> OrchestrationState:
    return {
        "execution_id": str(exec_id),
        "project_id": str(project.id),
        "objective": objective,
        "ingestion_operation_token": operation_token,
        "tasks": tasks,
        "completed_task_ids": [t["task_id"] for t in tasks],
        "verification_results": [],
        "artifacts": [],
    }


async def _count(model, *where) -> int:
    """Count rows using a fresh session so results reflect committed PostgreSQL state."""
    async with AsyncSessionLocal() as session:
        stmt = select(func.count()).select_from(model)
        for clause in where:
            stmt = stmt.where(clause)
        return int((await session.execute(stmt)).scalar_one())


async def _fetch_all(model, *where) -> list:
    async with AsyncSessionLocal() as session:
        stmt = select(model).execution_options(populate_existing=True)
        for clause in where:
            stmt = stmt.where(clause)
        return list((await session.execute(stmt)).scalars().all())


# ==============================================================================
# 1-3. First ingestion, exact retry, and new batch in the same execution
# ==============================================================================


@pytest.mark.asyncio
async def test_first_ingestion_creates_expected_memories_and_audits(db_session: AsyncSession):
    project, exec_row = await _seed_project_and_execution(db_session, "First Ingest")
    token = f"{exec_row.id}:wave_1"
    state = _build_state(project, exec_row.id, token, [_arch_task()])

    result = await ingest_knowledge_node(state)

    assert result["ingestion_status"] == "completed"
    assert len(result["ingested_memory_ids"]) == 2

    ops = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project.id)
    assert len(ops) == 1
    assert ops[0].status == IngestionOperationStatus.COMPLETED
    assert ops[0].operation_token == token

    memories = await _fetch_all(ProjectMemory, ProjectMemory.project_id == project.id)
    assert len(memories) == 2
    for mem in memories:
        assert mem.fingerprint is not None
        assert len(mem.fingerprint) == 64
        assert mem.ingestion_operation_id == ops[0].id

    audits = await _fetch_all(
        MemoryAuditLog,
        MemoryAuditLog.project_id == project.id,
        MemoryAuditLog.action == MemoryAuditAction.CREATED,
    )
    assert len(audits) == 2


@pytest.mark.asyncio
async def test_exact_retry_creates_no_duplicates(db_session: AsyncSession):
    project, exec_row = await _seed_project_and_execution(db_session, "Exact Retry")
    token = f"{exec_row.id}:wave_1"
    state = _build_state(project, exec_row.id, token, [_arch_task()])

    first = await ingest_knowledge_node(state)
    second = await ingest_knowledge_node(copy.deepcopy(state))

    assert second["ingestion_status"] == "completed"
    assert second["ingested_memory_ids"] == first["ingested_memory_ids"]

    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 2
    assert await _count(MemoryAuditLog, MemoryAuditLog.project_id == project.id) == 2
    assert (
        await _count(
            IngestionOperation,
            IngestionOperation.project_id == project.id,
            IngestionOperation.operation_token == token,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_new_batch_in_same_execution_creates_legitimate_new_memories(
    db_session: AsyncSession,
):
    project, exec_row = await _seed_project_and_execution(db_session, "Wave Two")
    exec_id = exec_row.id

    wave_1 = _build_state(project, exec_id, f"{exec_id}:wave_1", [_arch_task()])
    await ingest_knowledge_node(wave_1)
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 2

    # Same execution, new operation token, new completed task.
    wave_2 = _build_state(
        project,
        exec_id,
        f"{exec_id}:wave_2",
        [_arch_task(), _backend_task(6)],
    )
    result = await ingest_knowledge_node(wave_2)

    assert result["ingestion_status"] == "completed"
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 3

    ops = await _fetch_all(
        IngestionOperation,
        IngestionOperation.project_id == project.id,
        IngestionOperation.execution_id == exec_id,
    )
    assert len(ops) == 2
    assert {op.operation_token for op in ops} == {f"{exec_id}:wave_1", f"{exec_id}:wave_2"}

    # The new backend decision must exist and not have been suppressed.
    new_rows = await _fetch_all(
        ProjectMemory,
        ProjectMemory.project_id == project.id,
        ProjectMemory.source_task_id == "task-6-backend",
    )
    assert len(new_rows) == 1
    assert new_rows[0].category == MemoryCategory.DECISION


# ==============================================================================
# 4-5. Concurrency
# ==============================================================================


@pytest.mark.asyncio
async def test_ten_concurrent_requests_same_operation_create_zero_duplicates(
    db_session: AsyncSession,
):
    project, exec_row = await _seed_project_and_execution(db_session, "Concurrent Same Op")
    token = f"{exec_row.id}:wave_1"
    state = _build_state(project, exec_row.id, token, [_arch_task()])
    candidate_count = 2

    results = await asyncio.gather(
        *[ingest_knowledge_node(copy.deepcopy(state)) for _ in range(10)],
        return_exceptions=True,
    )

    # No raised exceptions, and every request reports success.
    assert not [r for r in results if isinstance(r, BaseException)]
    assert all(r["ingestion_status"] == "completed" for r in results)

    # All requests resolve to the identical memory ID set.
    id_sets = {tuple(sorted(r["ingested_memory_ids"])) for r in results}
    assert len(id_sets) == 1
    assert len(next(iter(id_sets))) == candidate_count

    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == candidate_count
    assert await _count(MemoryAuditLog, MemoryAuditLog.project_id == project.id) == candidate_count
    assert (
        await _count(
            IngestionOperation,
            IngestionOperation.project_id == project.id,
            IngestionOperation.operation_token == token,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_requests_different_operations_do_not_suppress(
    db_session: AsyncSession,
):
    project, exec_row = await _seed_project_and_execution(db_session, "Concurrent Distinct")
    exec_id = exec_row.id
    op_count = 5

    states = [
        _build_state(
            project,
            exec_id,
            f"{exec_id}:wave_{i}",
            [_arch_task(task_id=f"task-arch-{i}")],
            objective=f"{OBJECTIVE} variant {i}",
        )
        for i in range(op_count)
    ]
    # Distinct task titles so each operation contributes its own decision memory.
    for i, state in enumerate(states):
        state["tasks"][0]["title"] = f"Conduct Architecture & System Design wave {i}"
        state["completed_task_ids"] = [f"task-arch-{i}"]

    results = await asyncio.gather(
        *[ingest_knowledge_node(copy.deepcopy(s)) for s in states],
        return_exceptions=True,
    )

    assert not [r for r in results if isinstance(r, BaseException)]
    assert all(r["ingestion_status"] == "completed" for r in results)
    assert all(len(r["ingested_memory_ids"]) == 2 for r in results)

    # 2 candidates per operation: one milestone and one decision, none suppressed.
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 2 * op_count
    assert (
        await _count(
            IngestionOperation,
            IngestionOperation.project_id == project.id,
            IngestionOperation.status == IngestionOperationStatus.COMPLETED,
        )
        == op_count
    )


# ==============================================================================
# 6-7. Failure handling and recovery
# ==============================================================================


@pytest.mark.asyncio
async def test_failure_midway_rolls_back_appropriate_transaction(
    db_session: AsyncSession, monkeypatch
):
    project, exec_row = await _seed_project_and_execution(db_session, "Midway Failure")
    token = f"{exec_row.id}:wave_1"
    state = _build_state(project, exec_row.id, token, [_arch_task()])

    original_create = MemoryService.create_memory

    async def failing_create(db, *args, **kwargs):
        # Write the row inside the candidate's savepoint, then fail. The savepoint
        # must roll back this row and its CREATED audit entry.
        if kwargs.get("summary") == ARCH_TITLE:
            await original_create(db, *args, **kwargs)
            raise RuntimeError("simulated constraint violation on decision candidate")
        return await original_create(db, *args, **kwargs)

    monkeypatch.setattr(MemoryService, "create_memory", staticmethod(failing_create))

    result = await ingest_knowledge_node(state)

    # Error is captured, not raised; the operation still commits as partial.
    assert result["ingestion_status"] == "partial"
    assert len(result["ingestion_errors"]) == 1
    assert "simulated constraint violation" in result["ingestion_errors"][0]
    assert len(result["ingested_memory_ids"]) == 1

    # Only the milestone survived; the failed candidate left no rows behind.
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 1
    assert await _count(MemoryAuditLog, MemoryAuditLog.project_id == project.id) == 1

    ops = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project.id)
    assert len(ops) == 1
    assert ops[0].status == IngestionOperationStatus.COMPLETED
    assert "simulated constraint violation" in (ops[0].error_message or "")


@pytest.mark.asyncio
async def test_retry_after_failed_operation_succeeds(db_session: AsyncSession):
    project, exec_row = await _seed_project_and_execution(db_session, "Retry After Fail")
    token = f"{exec_row.id}:wave_1"
    state = _build_state(project, exec_row.id, token, [_arch_task()])

    # Simulate a top-level failure at the final commit stage. The per-candidate
    # savepoints do not catch this, so the operation is marked FAILED.
    failing_clock = MagicMock()
    failing_clock.now.side_effect = RuntimeError("simulated commit-stage failure")
    with patch("app.orchestrator.workflow_graph.datetime", failing_clock):
        failed = await ingest_knowledge_node(copy.deepcopy(state))

    assert failed["ingestion_status"] == "failed"
    assert failed["ingested_memory_ids"] == []
    # The failed attempt must not leak memories.
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 0

    ops = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project.id)
    assert len(ops) == 1
    assert ops[0].status == IngestionOperationStatus.FAILED
    assert "simulated commit-stage failure" in (ops[0].error_message or "")

    # Correct the cause (patch removed) and retry with the same token.
    retried = await ingest_knowledge_node(copy.deepcopy(state))

    assert retried["ingestion_status"] == "completed"
    assert len(retried["ingested_memory_ids"]) == 2
    assert await _count(ProjectMemory, ProjectMemory.project_id == project.id) == 2
    assert (
        await _count(
            IngestionOperation,
            IngestionOperation.project_id == project.id,
            IngestionOperation.operation_token == token,
        )
        == 1
    )

    ops = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project.id)
    assert ops[0].status == IngestionOperationStatus.COMPLETED
    assert ops[0].error_message is None


# ==============================================================================
# 8-10. Existing behaviour preserved for ingested memories
# ==============================================================================


@pytest.mark.asyncio
async def test_existing_revision_history_remains_intact(db_session: AsyncSession):
    project, exec_row = await _seed_project_and_execution(db_session, "Revisions")
    state = _build_state(project, exec_row.id, f"{exec_row.id}:wave_1", [_arch_task()])
    await ingest_knowledge_node(state)

    decision_rows = await _fetch_all(
        ProjectMemory,
        ProjectMemory.project_id == project.id,
        ProjectMemory.category == MemoryCategory.DECISION,
    )
    assert len(decision_rows) == 1
    decision_id = decision_rows[0].id

    async with AsyncSessionLocal() as session:
        updated = await MemoryService.update_memory(
            session,
            project.id,
            decision_id,
            content="Use idempotent event processing with Redis dedup keys and a DB unique index.",
            expected_revision=1,
            actor_type="user",
            actor_id="tester",
            reason="Refined after review",
        )
        await session.commit()
        new_id = updated.id

    assert updated.revision == 2
    assert updated.previous_revision_id == decision_id

    original = (await _fetch_all(ProjectMemory, ProjectMemory.id == decision_id))[0]
    assert original.status == MemoryStatus.SUPERSEDED
    assert original.fingerprint is not None

    async with AsyncSessionLocal() as session:
        history = await MemoryService.get_revision_history(session, project.id, new_id)
    assert [m.revision for m in history] == [1, 2]

    updates = await _fetch_all(
        MemoryAuditLog,
        MemoryAuditLog.project_id == project.id,
        MemoryAuditLog.action == MemoryAuditAction.UPDATED,
    )
    assert len(updates) >= 1
    assert any(a.actor_id == "tester" for a in updates)


@pytest.mark.asyncio
async def test_existing_conflict_detection_remains_correct(db_session: AsyncSession):
    project, exec_row = await _seed_project_and_execution(db_session, "Conflicts")

    # A competing ACTIVE memory under the same summary as the ingested decision.
    competitor = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary=ARCH_TITLE,
        content="Use a single-writer queue with no deduplication keys at all.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    state = _build_state(project, exec_row.id, f"{exec_row.id}:wave_1", [_arch_task()])
    result = await ingest_knowledge_node(state)
    assert result["ingestion_status"] == "completed"

    decision_rows = await _fetch_all(
        ProjectMemory,
        ProjectMemory.project_id == project.id,
        ProjectMemory.summary == ARCH_TITLE,
        ProjectMemory.fingerprint.is_not(None),
    )
    assert len(decision_rows) == 1
    ingested = decision_rows[0]
    assert ingested.conflict_status == MemoryConflictStatus.DETECTED
    assert ingested.conflicting_memory_id == competitor.id

    partner = (await _fetch_all(ProjectMemory, ProjectMemory.id == competitor.id))[0]
    assert partner.conflict_status == MemoryConflictStatus.DETECTED
    assert partner.conflicting_memory_id == ingested.id

    conflict_audits = await _fetch_all(
        MemoryAuditLog,
        MemoryAuditLog.memory_id == ingested.id,
        MemoryAuditLog.action == MemoryAuditAction.CONFLICT_DETECTED,
    )
    assert len(conflict_audits) == 1


@pytest.mark.asyncio
async def test_existing_project_isolation_remains_intact(db_session: AsyncSession):
    project_a, exec_a = await _seed_project_and_execution(db_session, "Isolation A")
    project_b, exec_b = await _seed_project_and_execution(db_session, "Isolation B")

    # Identical candidate data; the same operation token string in both projects.
    token = "shared-operation-token:wave_1"
    state_a = _build_state(project_a, exec_a.id, token, [_arch_task()])
    state_b = _build_state(project_b, exec_b.id, token, [_arch_task()])

    result_a, result_b = await asyncio.gather(
        ingest_knowledge_node(state_a),
        ingest_knowledge_node(state_b),
    )

    assert result_a["ingestion_status"] == "completed"
    assert result_b["ingestion_status"] == "completed"
    assert set(result_a["ingested_memory_ids"]).isdisjoint(result_b["ingested_memory_ids"])

    mems_a = await _fetch_all(ProjectMemory, ProjectMemory.project_id == project_a.id)
    mems_b = await _fetch_all(ProjectMemory, ProjectMemory.project_id == project_b.id)
    assert len(mems_a) == 2
    assert len(mems_b) == 2

    fp_a = {m.fingerprint for m in mems_a}
    fp_b = {m.fingerprint for m in mems_b}
    assert fp_a.isdisjoint(fp_b)

    # Each project has its own operation row under the shared token.
    ops_a = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project_a.id)
    ops_b = await _fetch_all(IngestionOperation, IngestionOperation.project_id == project_b.id)
    assert len(ops_a) == 1 and len(ops_b) == 1
    assert ops_a[0].id != ops_b[0].id
    assert all(m.ingestion_operation_id == ops_a[0].id for m in mems_a)
    assert all(m.ingestion_operation_id == ops_b[0].id for m in mems_b)


# ==============================================================================
# 11. Direct database constraint
# ==============================================================================


@pytest.mark.asyncio
async def test_database_fingerprint_uniqueness_constraint_directly(db_session: AsyncSession):
    project, _ = await _seed_project_and_execution(db_session, "Constraint")
    fingerprint = "a" * 64

    def _row() -> ProjectMemory:
        return ProjectMemory(
            project_id=project.id,
            category=MemoryCategory.DECISION,
            summary="Constraint probe decision",
            content="Probe row used to exercise the fingerprint unique index.",
            provenance_type=MemoryProvenanceType.VERIFIED_FINDING,
            confidence_score=0.9,
            is_verified=True,
            status=MemoryStatus.ACTIVE,
            revision=1,
            conflict_status=MemoryConflictStatus.NONE,
            metadata_json={},
            fingerprint=fingerprint,
        )

    async with AsyncSessionLocal() as session:
        session.add(_row())
        session.add(_row())
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    # The first row alone is accepted by the same constraint.
    async with AsyncSessionLocal() as session:
        session.add(_row())
        await session.commit()

    assert (
        await _count(
            ProjectMemory,
            ProjectMemory.project_id == project.id,
            ProjectMemory.fingerprint == fingerprint,
        )
        == 1
    )
