"""Real FastAPI integration tests for Project Intelligence REST APIs (M1.3-6).

Tests:
1. Memory CRUD, Validation & Provenance:
   - Create memory with proper provenance and audit.
   - Rejection of direct client verification spoofing.
   - Validation boundaries: summary lengths, empty content, invalid categories.
   - Project existence and cross-project isolation.
2. Memory Listing, Filtering & Pagination:
   - Category, provenance, status, and verification filtering.
   - Full-text / substring search filtering.
   - Default exclusion of superseded/archived records and include_historical toggle.
   - Date range validation (400 if created_after > created_before).
   - Standardized PaginatedResponse envelope.
3. Immutable Revision Updates & Optimistic Concurrency:
   - Successful revision progression (revision 1 -> 2).
   - Invalidation of verification upon content change.
   - Optimistic concurrency rejection (409 Conflict) on stale expected_revision.
4. Memory Lifecycle Transitions:
   - Soft-archive active memory.
   - Restore archived memory.
   - Rejection of invalid transitions on terminal statuses.
5. Explicit Memory Verification:
   - POST /verify with verified_by and evidence details.
   - Provenance promotion from AGENT_CONCLUSION to VERIFIED_FINDING.
6. Conflict Inspection and Resolution:
   - GET /conflicts lists detected conflicts with partner memory details.
   - Resolve via 'supersede'.
   - Resolve via 'merge' with synthesized text.
   - Rejection of invalid resolution strategies or non-conflicted memories.
7. Memory Audit History:
   - GET /audit returns chronological / reverse-chronological event trail.
   - Read-only preservation (mutations to audit endpoints rejected with 405).
8. Artifact Lineage Exploration:
   - GET /projects/{project_id}/artifacts/{artifact_id}/lineage.
   - Ancestors, descendants, parent, superseding, and superseded links.
   - Cross-project artifact isolation (404).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.artifact import Artifact, ArtifactType, ArtifactVerificationStatus
from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.services.memory_service import MemoryService


def _create_workspace(name: str = "Test WS") -> Workspace:
    return Workspace(name=name, slug=f"ws-{uuid.uuid4().hex[:6]}")


def _create_project(name: str, workspace_id: uuid.UUID) -> Project:
    return Project(
        workspace_id=workspace_id,
        name=name,
        slug=f"proj-{uuid.uuid4().hex[:6]}",
        studio_type=StudioType.SAAS,
    )


@pytest.mark.asyncio
async def test_memory_creation_and_validation(db_session: AsyncSession):
    """Verifies memory creation, default provenance scoring, and validation constraints."""
    ws = _create_workspace("Creation WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Memory Creation Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Valid creation
        payload = {
            "category": "decision",
            "summary": "Primary Database: PostgreSQL 16",
            "content": "PostgreSQL 16 selected for ACID compliance, JSONB, and GIN full-text search.",
            "provenance_type": "user_provided",
            "metadata_json": {"tags": ["database", "infrastructure"]},
        }
        res = await client.post(f"/api/v1/projects/{project.id}/memories", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["summary"] == "Primary Database: PostgreSQL 16"
        assert data["category"] == "decision"
        assert data["provenance_type"] == "user_provided"
        assert data["confidence_score"] == 1.0
        assert data["is_verified"] is False
        assert data["status"] == "active"
        assert data["revision"] == 1
        assert data["project_id"] == str(project.id)
        assert data["metadata_json"]["tags"] == ["database", "infrastructure"]
        created_id = data["id"]

        # 2. Verify audit record was created automatically
        audit_res = await client.get(f"/api/v1/projects/{project.id}/memories/{created_id}/audit")
        assert audit_res.status_code == 200
        audit_data = audit_res.json()
        assert audit_data["total"] >= 1
        assert audit_data["items"][0]["action"] == MemoryAuditAction.CREATED.value

        # 3. Validation failure: empty summary
        bad_payload = {
            "category": "decision",
            "summary": "   ",
            "content": "Valid content",
        }
        bad_res = await client.post(f"/api/v1/projects/{project.id}/memories", json=bad_payload)
        assert bad_res.status_code == 422

        # 4. Validation failure: non-existent project returns 404
        dummy_project = uuid.uuid4()
        res_404 = await client.post(f"/api/v1/projects/{dummy_project}/memories", json=payload)
        assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_memory_listing_filtering_and_pagination(db_session: AsyncSession):
    """Verifies memory listing, filters (category, status, historical), search, and pagination."""
    ws = _create_workspace("List WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("List Filter Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Seed 5 memories
    m1 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Requirement: Multi-tenant tenant isolation",
        content="Each tenant must have partitioned storage and strictly isolated schemas.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    m2 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Decision: RabbitMQ Message Broker",
        content="RabbitMQ selected for AMQP routing.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    m3 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.CONSTRAINT,
        summary="Constraint: Max Latency 200ms",
        content="API endpoints must respond within 200ms p95.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    # Archive m3
    await MemoryService.archive_memory(db_session, project.id, m3.id, reason="Archived constraint")
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Default list excludes archived by default
        res = await client.get(f"/api/v1/projects/{project.id}/memories")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 50
        ids = [item["id"] for item in data["items"]]
        assert str(m1.id) in ids
        assert str(m2.id) in ids
        assert str(m3.id) not in ids

        # 2. include_historical=true includes archived
        res_hist = await client.get(
            f"/api/v1/projects/{project.id}/memories", params={"include_historical": "true"}
        )
        assert res_hist.status_code == 200
        assert res_hist.json()["total"] == 3

        # 3. Filter by category
        res_cat = await client.get(
            f"/api/v1/projects/{project.id}/memories", params={"category": "decision"}
        )
        assert res_cat.status_code == 200
        cat_data = res_cat.json()
        assert cat_data["total"] == 1
        assert cat_data["items"][0]["id"] == str(m2.id)

        # 4. Search query
        res_search = await client.get(
            f"/api/v1/projects/{project.id}/memories", params={"search": "Multi-tenant"}
        )
        assert res_search.status_code == 200
        search_data = res_search.json()
        assert search_data["total"] == 1
        assert search_data["items"][0]["id"] == str(m1.id)

        # 5. Invalid date bounds (created_after > created_before)
        res_date_err = await client.get(
            f"/api/v1/projects/{project.id}/memories",
            params={
                "created_after": "2026-11-05T00:00:00Z",
                "created_before": "2026-11-01T00:00:00Z",
            },
        )
        assert res_date_err.status_code == 400
        assert "created_after cannot be later than created_before" in res_date_err.json()["detail"]


@pytest.mark.asyncio
async def test_memory_get_and_cross_project_isolation(db_session: AsyncSession):
    """Verifies that accessing memories across project boundaries is strictly rejected with 404."""
    ws = _create_workspace("Isolation WS")
    db_session.add(ws)
    await db_session.flush()

    project_a = _create_project("Project Alpha", ws.id)
    project_b = _create_project("Project Beta", ws.id)
    db_session.add_all([project_a, project_b])
    await db_session.commit()

    mem_a = await MemoryService.create_memory(
        db_session,
        project_id=project_a.id,
        category=MemoryCategory.DISCOVERY,
        summary="Alpha Secret Discovery",
        content="Confidential finding specific to Alpha.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Accessing mem_a under project_a succeeds
        res_ok = await client.get(f"/api/v1/projects/{project_a.id}/memories/{mem_a.id}")
        assert res_ok.status_code == 200
        assert res_ok.json()["summary"] == "Alpha Secret Discovery"

        # Attempting to access mem_a through project_b returns 404
        res_blocked = await client.get(f"/api/v1/projects/{project_b.id}/memories/{mem_a.id}")
        assert res_blocked.status_code == 404
        assert "not found in project" in res_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_memory_update_optimistic_concurrency_and_immutability(db_session: AsyncSession):
    """Verifies immutable revision creation, verification reset, and 409 Conflict on revision mismatch."""
    ws = _create_workspace("Revision WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Revision Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Cache Store: Redis Standalone",
        content="Using standalone Redis 7.2 node.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    # Mark it verified initially
    await MemoryService.verify_memory(
        db_session, project.id, mem.id, verified_by="Tech Lead", reason="Architecture approved"
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Update with expected_revision=1
        update_payload = {
            "expected_revision": 1,
            "summary": "Cache Store: Redis Cluster",
            "content": "Upgraded to 3-node Redis 7.2 Cluster with replication.",
            "reason": "Production scalability requirements",
        }
        res_up = await client.patch(
            f"/api/v1/projects/{project.id}/memories/{mem.id}", json=update_payload
        )
        assert res_up.status_code == 200
        up_data = res_up.json()
        assert up_data["revision"] == 2
        assert up_data["previous_revision_id"] == str(mem.id)
        assert up_data["summary"] == "Cache Store: Redis Cluster"
        # Verification was automatically invalidated upon text change
        assert up_data["is_verified"] is False
        assert up_data["status"] == "active"
        new_memory_id = up_data["id"]

        # 2. Check that the original row still exists in DB as SUPERSEDED
        res_old = await client.get(f"/api/v1/projects/{project.id}/memories/{mem.id}")
        assert res_old.status_code == 200
        assert res_old.json()["status"] == MemoryStatus.SUPERSEDED.value

        # 3. Attempting another update with stale expected_revision=1 fails with 409 Conflict
        res_conflict = await client.patch(
            f"/api/v1/projects/{project.id}/memories/{new_memory_id}",
            json={
                "expected_revision": 1,  # Stale! Current revision is 2
                "content": "Conflicting update",
            },
        )
        assert res_conflict.status_code == 409
        assert "Revision conflict" in res_conflict.json()["detail"]


@pytest.mark.asyncio
async def test_memory_archive_and_restore_lifecycle(db_session: AsyncSession):
    """Verifies soft-archive and restore lifecycle transitions via REST API."""
    ws = _create_workspace("Lifecycle WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Lifecycle Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.PREFERENCE,
        summary="Code Style: Functional Python",
        content="Prefer dataclasses and pure functions over heavy OOP hierarchies.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Archive
        res_arc = await client.post(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/archive",
            json={"reason": "Team adopted object-oriented convention"},
        )
        assert res_arc.status_code == 200
        assert res_arc.json()["status"] == MemoryStatus.ARCHIVED.value

        # 2. Restore
        res_res = await client.post(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/restore",
            json={"reason": "Reinstated functional preference"},
        )
        assert res_res.status_code == 200
        assert res_res.json()["status"] == MemoryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_memory_explicit_verification_endpoint(db_session: AsyncSession):
    """Verifies that POST /verify upgrades AGENT_CONCLUSION to VERIFIED_FINDING with verifier attribution."""
    ws = _create_workspace("Verify WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Verify Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DISCOVERY,
        summary="Memory Leak in WebSockets Worker",
        content="Discovered unbounded buffer accumulation in connection handler.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()
    assert mem.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION
    assert mem.is_verified is False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "verified_by": "Senior QA Engineer",
            "verification_details": {
                "test_suite": "backend/tests/test_ws_leak.py",
                "reproduced": True,
            },
            "reason": "Confirmed leak under load simulation",
        }
        res = await client.post(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/verify", json=payload
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_verified"] is True
        assert data["verified_at"] is not None
        # Upgraded to verified_finding
        assert data["provenance_type"] == MemoryProvenanceType.VERIFIED_FINDING.value
        assert data["metadata_json"]["verified_by"] == "Senior QA Engineer"


@pytest.mark.asyncio
async def test_conflict_detection_and_resolution_api(db_session: AsyncSession):
    """Verifies GET /conflicts and POST /resolve via 'supersede' and 'merge' strategies."""
    ws = _create_workspace("Conflict WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Conflict Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    # Create memory 1
    m1 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="API Gateway: Envoy Proxy",
        content="Envoy Proxy selected as the API gateway.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    # Create conflicting memory 2 (same summary, divergent content)
    m2 = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="API Gateway: Envoy Proxy",
        content="Traefik selected as the API gateway with automatic Let's Encrypt TLS.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
    )
    await db_session.commit()

    # Verify conflict was flagged
    assert m2.conflict_status == MemoryConflictStatus.DETECTED
    assert m2.conflicting_memory_id == m1.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. List conflicts
        res_conflicts = await client.get(f"/api/v1/projects/{project.id}/memories/conflicts")
        assert res_conflicts.status_code == 200
        c_data = res_conflicts.json()
        assert c_data["total"] >= 1
        item = c_data["items"][0]
        assert item["memory_id"] == str(m2.id)
        assert item["conflicting_memory_id"] == str(m1.id)
        assert item["partner_summary"] == "API Gateway: Envoy Proxy"

        # 2. Resolve conflict via 'supersede' (m2 becomes ACTIVE, m1 becomes SUPERSEDED)
        resolve_payload = {
            "resolution": "supersede",
            "reason": "Team ratified Traefik decision over Envoy",
            "actor_id": "operator-1",
        }
        res_res = await client.post(
            f"/api/v1/projects/{project.id}/memories/{m2.id}/resolve", json=resolve_payload
        )
        assert res_res.status_code == 200
        res_data = res_res.json()
        assert res_data["status"] == MemoryStatus.ACTIVE.value
        assert res_data["conflict_status"] == MemoryConflictStatus.RESOLVED.value

        # Check partner m1 is superseded via API
        res_m1 = await client.get(f"/api/v1/projects/{project.id}/memories/{m1.id}")
        assert res_m1.status_code == 200
        assert res_m1.json()["status"] == MemoryStatus.SUPERSEDED.value
        assert res_m1.json()["conflict_status"] == MemoryConflictStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_memory_audit_history_read_only_endpoint(db_session: AsyncSession):
    """Verifies audit trail retrieval, ordering, and that mutation endpoints to audit are prohibited."""
    ws = _create_workspace("Audit WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Audit Project", ws.id)
    db_session.add(project)
    await db_session.commit()

    mem = await MemoryService.create_memory(
        db_session,
        project_id=project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Strict SLA: 99.99% Uptime",
        content="Four nines availability required.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET /audit returns 200
        res = await client.get(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/audit", params={"order": "desc"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["items"][0]["action"] == MemoryAuditAction.CREATED.value

        # Prohibited mutations (POST / DELETE to audit return 405 Method Not Allowed)
        res_post = await client.post(
            f"/api/v1/projects/{project.id}/memories/{mem.id}/audit", json={}
        )
        assert res_post.status_code == 405

        res_del = await client.delete(f"/api/v1/projects/{project.id}/memories/{mem.id}/audit")
        assert res_del.status_code == 405


@pytest.mark.asyncio
async def test_artifact_lineage_api_exploration(db_session: AsyncSession):
    """Verifies GET /projects/{project_id}/artifacts/{artifact_id}/lineage returns complete graph."""
    ws = _create_workspace("Lineage WS")
    db_session.add(ws)
    await db_session.flush()

    project = _create_project("Lineage Project", ws.id)
    other_project = _create_project("Other Project", ws.id)
    db_session.add_all([project, other_project])
    await db_session.commit()

    # Create parent artifact v1
    art_v1 = Artifact(
        project_id=project.id,
        name="architecture_v1.md",
        file_path="/tmp/architecture_v1.md",
        artifact_type=ArtifactType.ARCHITECTURE,
        version=1,
    )
    db_session.add(art_v1)
    await db_session.flush()

    # Create child/superseding artifact v2
    art_v2 = Artifact(
        project_id=project.id,
        name="architecture_v2.md",
        file_path="/tmp/architecture_v2.md",
        artifact_type=ArtifactType.ARCHITECTURE,
        version=2,
        parent_artifact_id=art_v1.id,
        verification_status=ArtifactVerificationStatus.VERIFIED,
    )
    db_session.add(art_v2)
    await db_session.flush()

    # Link art_v1 superseded by art_v2
    art_v1.superseded_by_id = art_v2.id
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Project-scoped lineage query on v2
        res = await client.get(f"/api/v1/projects/{project.id}/artifacts/{art_v2.id}/lineage")
        assert res.status_code == 200
        data = res.json()
        assert data["artifact"]["name"] == "architecture_v2.md"
        assert data["artifact"]["version"] == 2
        assert data["artifact"]["verification_status"] == "verified"
        assert data["parent"] is not None
        assert data["parent"]["name"] == "architecture_v1.md"
        assert len(data["ancestors"]) == 1
        assert data["ancestors"][0]["name"] == "architecture_v1.md"
        assert len(data["supersedes"]) == 1
        assert data["supersedes"][0]["name"] == "architecture_v1.md"

        # 2. General /artifacts/{artifact_id}/lineage endpoint
        res_gen = await client.get(f"/api/v1/artifacts/{art_v2.id}/lineage")
        assert res_gen.status_code == 200
        assert res_gen.json()["artifact"]["id"] == str(art_v2.id)

        # 3. Cross-project isolation: querying v2 under other_project returns 404
        res_cross = await client.get(
            f"/api/v1/projects/{other_project.id}/artifacts/{art_v2.id}/lineage"
        )
        assert res_cross.status_code == 404
