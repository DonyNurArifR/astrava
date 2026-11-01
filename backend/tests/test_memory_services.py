import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_service import MemoryService


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


@pytest.mark.asyncio
async def test_memory_crud_and_project_isolation(db_session: AsyncSession):
    """Verifies scoped memory creation, retrieval, filtering, and strict project boundary isolation."""
    ws = create_workspace("CRUD Workspace")
    db_session.add(ws)
    await db_session.flush()

    proj_a = create_project("Project A", ws.id, StudioType.SAAS)
    proj_b = create_project("Project B", ws.id, StudioType.MEDIA)
    db_session.add_all([proj_a, proj_b])
    await db_session.commit()

    # 1. Create memories in Project A
    mem_a1 = await MemoryService.create_memory(
        db_session,
        project_id=proj_a.id,
        category=MemoryCategory.OBJECTIVE,
        summary="Build Payment Microservice",
        content="Support Stripe and PayPal webhooks with tenant isolation.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        actor_id="lead-architect",
        reason="Initial project objective",
    )
    mem_a2 = await MemoryService.create_memory(
        db_session,
        project_id=proj_a.id,
        category=MemoryCategory.CONSTRAINT,
        summary="Max Webhook Latency 200ms",
        content="Webhook ingestion must acknowledge within 200ms SLA.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )

    # 2. Create memory in Project B
    mem_b1 = await MemoryService.create_memory(
        db_session,
        project_id=proj_b.id,
        category=MemoryCategory.OBJECTIVE,
        summary="Create Video Campaign",
        content="Produce YouTube series on AI agents.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # Verify retrieval by ID with project scoping
    found_a1 = await MemoryService.get_memory(db_session, proj_a.id, mem_a1.id)
    assert found_a1 is not None
    assert found_a1.summary == "Build Payment Microservice"

    # Cross-project access must return None
    cross_access = await MemoryService.get_memory(db_session, proj_b.id, mem_a1.id)
    assert cross_access is None

    # Verify list filtering for Project A
    mems_a = await MemoryService.list_memories(db_session, proj_a.id)
    assert len(mems_a) == 2

    # Filter by category
    constraints_a = await MemoryService.list_memories(
        db_session, proj_a.id, category=MemoryCategory.CONSTRAINT
    )
    assert len(constraints_a) == 1
    assert constraints_a[0].id == mem_a2.id

    # Filter for Project B
    mems_b = await MemoryService.list_memories(db_session, proj_b.id)
    assert len(mems_b) == 1
    assert mems_b[0].id == mem_b1.id


@pytest.mark.asyncio
async def test_provenance_and_verification_rules(db_session: AsyncSession):
    """Verifies policy weights, unverified agent conclusion defaults, and authorized promotion."""
    ws = create_workspace("Provenance Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Provenance Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Agent conclusion without verifier -> must NOT be verified
    agent_mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="FastAPI vs Django",
        content="Use FastAPI for async performance.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
        source_agent_slug="solution-architect",
    )
    await db_session.commit()

    assert agent_mem.confidence_score == 0.70
    assert agent_mem.is_verified is False
    assert agent_mem.status == MemoryStatus.PROPOSED
    assert agent_mem.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION

    # Explicit promotion via verify_memory
    verified_mem = await MemoryService.verify_memory(
        db_session,
        project_id=project.id,
        memory_id=agent_mem.id,
        verified_by="engine:pytest_runner",
        verification_details={"test_suite": "tests/test_performance.py", "exit_code": 0},
        actor_id="qa-lead",
        reason="Performance benchmarks passed SLA",
    )
    await db_session.commit()

    assert verified_mem.is_verified is True
    assert verified_mem.verified_at is not None
    assert verified_mem.metadata_json["verified_by"] == "engine:pytest_runner"
    assert verified_mem.provenance_type == MemoryProvenanceType.VERIFIED_FINDING

    # Verify audit log was recorded
    audit_logs = await MemoryAuditService.list_by_memory(db_session, agent_mem.id, project.id)
    actions = [a.action for a in audit_logs]
    assert MemoryAuditAction.CREATED in actions
    assert MemoryAuditAction.VERIFIED in actions

    # Rejection of empty verifier
    with pytest.raises(ValueError, match="verified_by must be a non-empty string"):
        await MemoryService.verify_memory(db_session, project.id, agent_mem.id, verified_by="")


@pytest.mark.asyncio
async def test_immutable_revisions_and_optimistic_concurrency(db_session: AsyncSession):
    """Verifies immutable revision chains and optimistic concurrency collision detection."""
    ws = create_workspace("Revision Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Revision Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Step 1: Create rev 1
    rev1 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Cache Store: Redis Standalone",
        content="Use Redis standalone instance for session tokens.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()
    assert rev1.revision == 1

    # Step 2: Update with matching expected_revision=1 -> produces rev 2
    rev2 = await MemoryService.update_memory(
        db_session,
        project_id=project.id,
        memory_id=rev1.id,
        summary="Cache Store: Redis Cluster",
        content="Upgraded to Redis Cluster with sentinel failover.",
        expected_revision=1,
        actor_id="devops-lead",
        reason="High availability requirement",
    )
    await db_session.commit()

    assert rev2.revision == 2
    assert rev2.previous_revision_id == rev1.id
    assert rev2.status == MemoryStatus.ACTIVE

    # Reload rev 1 -> must be marked SUPERSEDED
    reloaded_rev1 = await MemoryService.get_memory(db_session, project.id, rev1.id)
    assert reloaded_rev1.status == MemoryStatus.SUPERSEDED

    # Step 3: Attempting update with stale expected_revision=1 on rev2 must raise ValueError
    with pytest.raises(ValueError, match="Revision conflict"):
        await MemoryService.update_memory(
            db_session,
            project_id=project.id,
            memory_id=rev2.id,
            content="Stale write",
            expected_revision=1,  # rev2 is revision 2, so 1 is stale!
        )

    # Step 4: Verify revision history traversal returns both in order
    history = await MemoryService.get_revision_history(db_session, project.id, rev2.id)
    assert len(history) == 2
    assert history[0].revision == 1
    assert history[0].summary == "Cache Store: Redis Standalone"
    assert history[1].revision == 2
    assert history[1].summary == "Cache Store: Redis Cluster"


@pytest.mark.asyncio
async def test_concurrent_updates_concurrency_race(db_session: AsyncSession):
    """Verifies that simultaneous updates competing on the same revision are caught by optimistic concurrency control."""
    ws = create_workspace("Race Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Race Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    base_mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Message Broker: RabbitMQ",
        content="Initial broker choice.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()
    mem_id = base_mem.id

    from app.db.session import AsyncSessionLocal

    async def worker_update(new_content: str, expected_rev: int):
        async with AsyncSessionLocal() as session:
            try:
                res = await MemoryService.update_memory(
                    session,
                    project_id=project.id,
                    memory_id=mem_id,
                    content=new_content,
                    expected_revision=expected_rev,
                )
                await session.commit()
                return ("success", res.revision)
            except Exception as e:
                await session.rollback()
                return ("error", str(e))

    # Two concurrent requests both expecting revision 1
    results = await asyncio.gather(
        worker_update("Update A: Kafka", 1),
        worker_update("Update B: NATS", 1),
    )

    successes = [r for r in results if r[0] == "success"]
    errors = [r for r in results if r[0] == "error"]

    # Exactly one must succeed in transitioning rev 1 -> rev 2; the other must fail due to revision conflict / terminal status
    assert len(successes) == 1
    assert len(errors) == 1
    assert "Revision conflict" in errors[0][1] or "superseded" in errors[0][1].lower()


@pytest.mark.asyncio
async def test_conflict_detection_and_resolution(db_session: AsyncSession):
    """Verifies deterministic conflict detection, link preservation, and supersede/merge/reject resolution."""
    ws = create_workspace("Conflict Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Conflict Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # 1. Existing active decision
    dec1 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Authentication Strategy",
        content="Use JWT tokens in HTTP-only cookies with 15-minute expiry.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # 2. Proposing a conflicting decision on the same topic
    dec2 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Authentication Strategy",  # Same summary!
        content="Use Server-Side Redis Sessions with opaque bearer tokens.",  # Different content!
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()

    # Conflict must be detected on both memories
    assert dec2.conflict_status == MemoryConflictStatus.DETECTED
    assert dec2.conflicting_memory_id == dec1.id

    reloaded_dec1 = await MemoryService.get_memory(db_session, project.id, dec1.id)
    assert reloaded_dec1.conflict_status == MemoryConflictStatus.DETECTED
    assert reloaded_dec1.conflicting_memory_id == dec2.id

    # 3. Resolve conflict with 'supersede'
    resolved = await MemoryService.resolve_conflict(
        db_session,
        project_id=project.id,
        memory_id=dec2.id,
        resolution="supersede",
        actor_id="security-architect",
        reason="Redis sessions required for instant revocation",
    )
    await db_session.commit()

    assert resolved.status == MemoryStatus.ACTIVE
    assert resolved.conflict_status == MemoryConflictStatus.RESOLVED

    reloaded_old = await MemoryService.get_memory(db_session, project.id, dec1.id)
    assert reloaded_old.status == MemoryStatus.SUPERSEDED
    assert reloaded_old.conflict_status == MemoryConflictStatus.RESOLVED


@pytest.mark.asyncio
async def test_audit_immutability_and_atomic_rollback(db_session: AsyncSession):
    """Verifies that audit records cannot be mutated/deleted and that failed transactions rollback cleanly."""
    ws = create_workspace("Audit Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Audit Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Compliance: GDPR Data Portability",
        content="Allow tenant users to export all historical invoices in JSON format.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # Verify audit log recorded for created memory
    created_logs = await MemoryAuditService.list_by_memory(db_session, mem.id, project.id)
    assert len(created_logs) == 1
    assert created_logs[0].action == MemoryAuditAction.CREATED

    # Immutability check on MemoryAuditService: update and delete MUST raise PermissionError
    with pytest.raises(PermissionError, match="immutable"):
        MemoryAuditService.update()

    with pytest.raises(PermissionError, match="immutable"):
        MemoryAuditService.delete()

    # Atomic rollback test: verify that a failure mid-transaction does not leave orphan memories or audit logs
    try:
        async with db_session.begin_nested():
            # Create a memory that flushes
            await MemoryService.create_memory(
                db_session,
                project_id=project.id,
                category=MemoryCategory.REQUIREMENT,
                summary="Temporary Requirement",
                content="This will be aborted.",
                provenance_type=MemoryProvenanceType.ASSUMPTION,
            )
            # Intentionally simulate an error
            raise RuntimeError("Simulated transaction failure")
    except RuntimeError:
        pass

    # Verify no uncommitted rows survived
    stmt = select(ProjectMemory).where(
        ProjectMemory.project_id == project.id,
        ProjectMemory.summary == "Temporary Requirement",
    )
    aborted_mem = (await db_session.execute(stmt)).scalar_one_or_none()
    assert aborted_mem is None


@pytest.mark.asyncio
async def test_memory_archive_restore_and_deletion_policies(db_session: AsyncSession):
    """Verifies soft-deletion (archiving), restoration, and compliance hard-deletion."""
    ws = create_workspace("Delete Workspace")
    db_session.add(ws)
    await db_session.flush()

    project = create_project("Delete Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DISCOVERY,
        summary="API Rate Limit Discovery",
        content="Third-party endpoint throttles at 100 req/min.",
        provenance_type=MemoryProvenanceType.VERIFIED_FINDING,
    )
    await db_session.commit()

    # 1. Soft delete (archive)
    archived = await MemoryService.archive_memory(
        db_session, project.id, mem.id, reason="Obsolete rate limit"
    )
    await db_session.commit()
    assert archived.status == MemoryStatus.ARCHIVED

    # By default, list_memories hides superseded but shows archived if explicitly requested
    active_mems = await MemoryService.list_memories(
        db_session, project.id, status=MemoryStatus.ACTIVE
    )
    assert len(active_mems) == 0

    # 2. Restore
    restored = await MemoryService.restore_memory(
        db_session, project.id, mem.id, reason="Rate limit still applies"
    )
    await db_session.commit()
    assert restored.status == MemoryStatus.ACTIVE

    # 3. Hard delete (compliance purge)
    deleted = await MemoryService.delete_memory(
        db_session, project.id, mem.id, hard_delete=True, reason="GDPR purge"
    )
    await db_session.commit()
    assert deleted is True

    # Memory row is gone
    gone = await MemoryService.get_memory(db_session, project.id, mem.id)
    assert gone is None

    # Audit log survives with memory_id=NULL and hard_deleted=True
    audit_logs = await MemoryAuditService.list_by_project(db_session, project.id)
    hard_delete_log = next(a for a in audit_logs if a.new_state and a.new_state.get("hard_deleted"))
    assert hard_delete_log is not None
    assert hard_delete_log.memory_id is None
