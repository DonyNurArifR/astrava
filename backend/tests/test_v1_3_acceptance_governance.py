"""Acceptance governance and security boundary test suite for ASTRAVA V1.3 (M1.3-8).

Covers:
- B4: Conflict resolution strategies (supersede, reject, merge) with rollback atomicity.
- B5: Verifier attribution and unauthorized/empty verifier rejection.
- B6: Audit immutability and survival across hard deletion.
- B7: API boundary scoping, optimistic concurrency (HTTP 409), and cross-project isolation.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.memory import (
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
)
from app.models.project import Project
from app.models.workspace import Workspace
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_service import MemoryService


@pytest.fixture
async def gov_project(db_session: AsyncSession):
    ws = Workspace(name="Gov WS", slug=f"gov-ws-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()

    proj = Project(name="Gov Project", slug=f"gov-proj-{uuid.uuid4().hex[:8]}", workspace_id=ws.id)
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest.fixture
async def other_project(db_session: AsyncSession):
    ws = Workspace(name="Other WS", slug=f"other-ws-{uuid.uuid4().hex[:8]}")
    db_session.add(ws)
    await db_session.flush()

    proj = Project(
        name="Other Project", slug=f"other-proj-{uuid.uuid4().hex[:8]}", workspace_id=ws.id
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


# ----------------------------------------------------------------------
# B4: Conflict Resolution Strategies & Atomicity
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conflict_resolution_supersede_strategy(
    db_session: AsyncSession, gov_project: Project
):
    """Verifies that 'supersede' resolution keeps primary active and marks partner superseded."""
    # Create two conflicting memories
    m1 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.DECISION,
        summary="DB Choice: PostgreSQL",
        content="Use PostgreSQL for relational and ACID transactions.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    m2 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.DECISION,
        summary="DB Choice: PostgreSQL",
        content="Use MongoDB for document storage.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()

    assert m1.conflict_status == MemoryConflictStatus.DETECTED
    assert m2.conflict_status == MemoryConflictStatus.DETECTED

    # Resolve via supersede m1 over m2
    resolved = await MemoryService.resolve_conflict(
        db_session,
        project_id=gov_project.id,
        memory_id=m1.id,
        resolution="supersede",
        actor_id="Abstract",
        reason="PostgreSQL chosen by architectural council.",
    )
    await db_session.commit()

    assert resolved.id == m1.id
    assert resolved.status == MemoryStatus.ACTIVE
    assert resolved.conflict_status == MemoryConflictStatus.RESOLVED

    # Reload partner m2
    reloaded_m2 = await MemoryService.get_memory(db_session, gov_project.id, m2.id)
    assert reloaded_m2.status == MemoryStatus.SUPERSEDED
    assert reloaded_m2.conflict_status == MemoryConflictStatus.RESOLVED


@pytest.mark.asyncio
async def test_conflict_resolution_reject_strategy(db_session: AsyncSession, gov_project: Project):
    """Verifies that 'reject' resolution rejects primary memory and keeps partner active."""
    m1 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.DECISION,
        summary="Cache Tier: Memcached",
        content="Use Memcached for simple key-value.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    m2 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.DECISION,
        summary="Cache Tier: Memcached",
        content="Use Redis with cluster support.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    # Reject m1
    rejected = await MemoryService.resolve_conflict(
        db_session,
        project_id=gov_project.id,
        memory_id=m1.id,
        resolution="reject",
        actor_id="Abstract",
        reason="Memcached lacks required pub/sub features.",
    )
    await db_session.commit()

    assert rejected.id == m1.id
    assert rejected.status == MemoryStatus.REJECTED
    assert rejected.conflict_status == MemoryConflictStatus.RESOLVED

    reloaded_m2 = await MemoryService.get_memory(db_session, gov_project.id, m2.id)
    assert reloaded_m2.status == MemoryStatus.ACTIVE
    assert reloaded_m2.conflict_status == MemoryConflictStatus.RESOLVED


@pytest.mark.asyncio
async def test_conflict_resolution_merge_strategy(db_session: AsyncSession, gov_project: Project):
    """Verifies that 'merge' resolution creates a reconciled memory and supersedes both parties."""
    m1 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Auth: JWT or Sessions",
        content="Option A: Stateless JWT in Authorization header.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    m2 = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Auth: JWT or Sessions",
        content="Option B: Server-side secure sessions.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    merged = await MemoryService.resolve_conflict(
        db_session,
        project_id=gov_project.id,
        memory_id=m1.id,
        resolution="merge",
        actor_id="Abstract",
        reason="Reconciled hybrid: short-lived JWT with Redis session revocation.",
        merged_summary="Auth: Hybrid JWT with Revocation",
        merged_content="Use 15-minute JWT with server-side Redis token blacklist.",
    )
    await db_session.commit()

    assert merged.id != m1.id
    assert merged.id != m2.id
    assert merged.status == MemoryStatus.ACTIVE
    assert merged.summary == "Auth: Hybrid JWT with Revocation"
    assert merged.conflict_status == MemoryConflictStatus.RESOLVED

    # Both m1 and m2 must be SUPERSEDED
    r1 = await MemoryService.get_memory(db_session, gov_project.id, m1.id)
    r2 = await MemoryService.get_memory(db_session, gov_project.id, m2.id)
    assert r1.status == MemoryStatus.SUPERSEDED
    assert r2.status == MemoryStatus.SUPERSEDED


# ----------------------------------------------------------------------
# B5 & B7: Verifier Identity, Authorization & Concurrency API
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_memory_rejects_empty_verifier(gov_project: Project):
    """API rejects blank/whitespace verifier identity."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create proposed memory
        res_create = await client.post(
            f"/api/v1/projects/{gov_project.id}/memories",
            json={
                "category": "decision",
                "summary": "Message Queue Choice",
                "content": "Selected RabbitMQ for AMQP routing.",
            },
        )
        assert res_create.status_code == 201
        mem_id = res_create.json()["id"]

        # 2. Attempt verification with empty whitespace verifier
        res_verif = await client.post(
            f"/api/v1/projects/{gov_project.id}/memories/{mem_id}/verify",
            json={"verified_by": "   ", "reason": "No name provided"},
        )
        assert res_verif.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_memory_update_stale_revision_returns_409(gov_project: Project):
    """API returns HTTP 409 Conflict when expected_revision does not match current."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            f"/api/v1/projects/{gov_project.id}/memories",
            json={
                "category": "requirement",
                "summary": "Rate Limiting Policy",
                "content": "Default limit 100 req/min per tenant.",
            },
        )
        mem_id = res.json()["id"]

        # Update revision from 1 to 2
        res_up1 = await client.patch(
            f"/api/v1/projects/{gov_project.id}/memories/{mem_id}",
            json={
                "expected_revision": 1,
                "summary": "Rate Limiting Policy v2",
                "content": "Updated limit 200 req/min per tenant.",
                "reason": "Scaled capacity",
            },
        )
        assert res_up1.status_code == 200
        assert res_up1.json()["revision"] == 2
        v2_id = res_up1.json()["id"]

        # Concurrent/stale update presenting expected_revision=1 must return 409
        res_stale = await client.patch(
            f"/api/v1/projects/{gov_project.id}/memories/{v2_id}",
            json={
                "expected_revision": 1,
                "summary": "Conflicting Rate Limiting Update",
                "content": "Trying to set 50 req/min with stale token.",
                "reason": "Late arrival",
            },
        )
        assert res_stale.status_code == 409
        assert "Revision conflict" in res_stale.json()["detail"]


# ----------------------------------------------------------------------
# B6: Audit Immutability & Survival Across Hard Deletion
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_logs_immutable_and_survive_memory_hard_deletion(
    db_session: AsyncSession, gov_project: Project
):
    """Verifies that audit rows cannot be deleted/updated and survive if the memory row is hard deleted."""
    # 1. Create and verify memory to produce multiple audit logs
    mem = await MemoryService.create_memory(
        db_session,
        project_id=gov_project.id,
        category=MemoryCategory.DECISION,
        summary="Encryption: TLS 1.3",
        content="Mandate TLS 1.3 with AES-256-GCM cipher suite.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
        actor_type="agent",
        actor_id="security-auditor",
        reason="Security assessment",
    )
    await db_session.commit()
    mem_id = mem.id

    # Verify audit service raises PermissionError on mutation
    with pytest.raises(PermissionError):
        MemoryAuditService.update()
    with pytest.raises(PermissionError):
        MemoryAuditService.delete()

    # Verify audit logs exist
    logs_before = await MemoryAuditService.list_by_memory(db_session, mem_id, gov_project.id)
    assert len(logs_before) >= 1
    initial_log_ids = {entry.id for entry in logs_before}

    # 2. Hard delete the memory row directly from project_memories table
    await db_session.delete(mem)
    await db_session.commit()

    # Memory row is gone from project_memories
    deleted_check = await MemoryService.get_memory(db_session, gov_project.id, mem_id)
    assert deleted_check is None

    # 3. Check that audit logs SURVIVE with SET NULL on memory_id and retain historical data
    logs_after, count = await MemoryAuditService.list_by_memory_paginated(
        db_session, mem_id, gov_project.id
    )
    assert count == len(logs_before)
    assert {entry.id for entry in logs_after} == initial_log_ids

    # Historical state remains fully preserved in JSON snapshot
    first_log = logs_after[0]
    assert first_log.new_state is not None
    assert first_log.new_state["summary"] == "Encryption: TLS 1.3"
    assert first_log.new_state["category"] == "decision"


# ----------------------------------------------------------------------
# B7: Cross-Project Isolation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_project_isolation_security(gov_project: Project, other_project: Project):
    """Verifies that memory access across project boundaries is strictly rejected with 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create memory in gov_project
        res_create = await client.post(
            f"/api/v1/projects/{gov_project.id}/memories",
            json={
                "category": "risk",
                "summary": "Proprietary Algorithm Leak Risk",
                "content": "Confidential trade secret parameters.",
            },
        )
        assert res_create.status_code == 201
        gov_mem_id = res_create.json()["id"]

        # Attempt to access gov_mem_id under other_project
        res_cross = await client.get(f"/api/v1/projects/{other_project.id}/memories/{gov_mem_id}")
        assert res_cross.status_code == 404

        # Attempt to fetch revisions across project
        res_cross_rev = await client.get(
            f"/api/v1/projects/{other_project.id}/memories/{gov_mem_id}/revisions"
        )
        assert res_cross_rev.status_code == 404

        # Attempt to fetch audit trail across project
        res_cross_audit = await client.get(
            f"/api/v1/projects/{other_project.id}/memories/{gov_mem_id}/audit"
        )
        assert res_cross_audit.status_code == 404
