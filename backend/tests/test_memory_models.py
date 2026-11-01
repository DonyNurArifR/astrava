import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact, ArtifactType, ArtifactVerificationStatus
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
async def test_project_memory_provenance_and_policy_weights(db_session: AsyncSession):
    """Verifies that all 4 provenance types are supported and that policy weights are distinct from verification status."""
    workspace = create_workspace("Intelligence Test Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Memory Provenance Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    # 1. User provided fact (policy weight 1.0, is_verified True)
    mem_user = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.REQUIREMENT,
        summary="Target Market: Enterprise B2B SaaS",
        content="The microservice must support multi-tenant billing with strict data isolation.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.0,
        is_verified=True,
        status=MemoryStatus.ACTIVE,
    )

    # 2. Agent conclusion (policy weight 0.70, NOT verified by default)
    mem_agent = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Use PostgreSQL Row-Level Security for tenant isolation",
        content="RLS provides declarative isolation at the database level without requiring multiple schemas.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
        confidence_score=0.70,
        is_verified=False,  # Agent conclusions must NOT be silently marked verified!
        status=MemoryStatus.PROPOSED,
    )

    # 3. Verified finding (policy weight 0.95, is_verified True via deterministic QA)
    mem_verified = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DISCOVERY,
        summary="Stripe Webhook Signature Verification Latency",
        content="Signature verification overhead measured at 2.4ms under 50 concurrent requests.",
        provenance_type=MemoryProvenanceType.VERIFIED_FINDING,
        confidence_score=0.95,
        is_verified=True,
        status=MemoryStatus.ACTIVE,
    )

    # 4. Assumption (policy weight 0.50, is_verified False)
    mem_assumption = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.CONSTRAINT,
        summary="Peak load estimate: 1,000 invoices per hour",
        content="Assumed peak volume during month-end dunning cycles.",
        provenance_type=MemoryProvenanceType.ASSUMPTION,
        confidence_score=0.50,
        is_verified=False,
        status=MemoryStatus.PROPOSED,
    )

    db_session.add_all([mem_user, mem_agent, mem_verified, mem_assumption])
    await db_session.commit()

    # Query back and verify persistence
    stmt = (
        select(ProjectMemory)
        .where(ProjectMemory.project_id == project.id)
        .order_by(ProjectMemory.confidence_score.desc())
    )
    result = await db_session.execute(stmt)
    memories = list(result.scalars().all())

    assert len(memories) == 4
    assert memories[0].provenance_type == MemoryProvenanceType.USER_PROVIDED
    assert memories[0].confidence_score == 1.0
    assert memories[0].is_verified is True

    # Confirm agent conclusion is not verified despite valid status
    agent_mem = next(
        m for m in memories if m.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION
    )
    assert agent_mem.confidence_score == 0.70
    assert agent_mem.is_verified is False
    assert agent_mem.status == MemoryStatus.PROPOSED


@pytest.mark.asyncio
async def test_project_memory_check_constraints(db_session: AsyncSession):
    """Verifies that database check constraints enforce valid confidence range and revision values."""
    workspace = create_workspace("Constraint Test Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Constraint Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    # 1. Confidence score > 1.0 must fail
    invalid_conf = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Invalid Confidence",
        content="Violates upper bound",
        provenance_type=MemoryProvenanceType.ASSUMPTION,
        confidence_score=1.5,
        is_verified=False,
    )
    db_session.add(invalid_conf)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Revision < 1 must fail
    invalid_rev = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Invalid Revision",
        content="Violates revision positive constraint",
        provenance_type=MemoryProvenanceType.ASSUMPTION,
        confidence_score=0.5,
        revision=0,
        is_verified=False,
    )
    db_session.add(invalid_rev)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_memory_revision_chain_and_audit_consistency(db_session: AsyncSession):
    """Verifies immutable revision chains and atomic audit log recording."""
    workspace = create_workspace("Revision Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Revision Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    # Step 1: Create initial revision 1 memory
    rev1 = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Database Choice: SQLite",
        content="Using SQLite for initial prototyping.",
        provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
        confidence_score=0.70,
        revision=1,
        status=MemoryStatus.ACTIVE,
    )
    db_session.add(rev1)
    await db_session.flush()

    audit1 = MemoryAuditLog(
        memory_id=rev1.id,
        project_id=project.id,
        action=MemoryAuditAction.CREATED,
        actor_type="agent",
        actor_id="solution-architect",
        new_state={"summary": rev1.summary, "revision": 1},
        reason="Initial architectural proposal",
    )
    db_session.add(audit1)
    await db_session.commit()

    # Step 2: Create revision 2 (superseding revision 1)
    rev2 = ProjectMemory(
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Database Choice: PostgreSQL 16",
        content="Migrated to PostgreSQL 16 for JSONB, RLS, and asyncpg support.",
        provenance_type=MemoryProvenanceType.VERIFIED_FINDING,
        confidence_score=0.95,
        is_verified=True,
        revision=2,
        previous_revision_id=rev1.id,
        status=MemoryStatus.ACTIVE,
    )
    db_session.add(rev2)
    await db_session.flush()

    # Mark revision 1 as superseded
    rev1.status = MemoryStatus.SUPERSEDED
    audit2 = MemoryAuditLog(
        memory_id=rev2.id,
        project_id=project.id,
        action=MemoryAuditAction.UPDATED,
        actor_type="user",
        actor_id="lead-architect",
        previous_state={"summary": rev1.summary, "revision": 1},
        new_state={"summary": rev2.summary, "revision": 2},
        reason="Upgraded requirement to enterprise PostgreSQL",
    )
    db_session.add(audit2)
    await db_session.commit()

    # Verify relationships
    stmt = select(ProjectMemory).where(ProjectMemory.id == rev2.id)
    reloaded_rev2 = (await db_session.execute(stmt)).scalar_one()

    assert reloaded_rev2.revision == 2
    assert reloaded_rev2.previous_revision is not None
    assert reloaded_rev2.previous_revision.id == rev1.id
    assert reloaded_rev2.previous_revision.status == MemoryStatus.SUPERSEDED

    # Verify audit trail
    audit_stmt = (
        select(MemoryAuditLog)
        .where(MemoryAuditLog.project_id == project.id)
        .order_by(MemoryAuditLog.created_at.asc())
    )
    audit_logs = list((await db_session.execute(audit_stmt)).scalars().all())
    assert len(audit_logs) == 2
    assert audit_logs[0].action == MemoryAuditAction.CREATED
    assert audit_logs[1].action == MemoryAuditAction.UPDATED
    assert audit_logs[1].reason == "Upgraded requirement to enterprise PostgreSQL"


@pytest.mark.asyncio
async def test_artifact_lineage_and_versioning(db_session: AsyncSession):
    """Verifies artifact versions, parent-child derivation, and supersession links."""
    workspace = create_workspace("Artifact Lineage Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Artifact Lineage Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    # 1. Base artifact: PRD v1
    prd_v1 = Artifact(
        project_id=project.id,
        name="prd.md",
        file_path="artifacts/prd_v1.md",
        artifact_type=ArtifactType.PRD,
        mime_type="text/markdown",
        file_size_bytes=4200,
        version=1,
        verification_status=ArtifactVerificationStatus.VERIFIED,
    )
    db_session.add(prd_v1)
    await db_session.flush()

    # 2. Derived artifact: Architecture v1 (parent is PRD v1)
    arch_v1 = Artifact(
        project_id=project.id,
        name="architecture.md",
        file_path="artifacts/architecture_v1.md",
        artifact_type=ArtifactType.ARCHITECTURE,
        mime_type="text/markdown",
        file_size_bytes=8400,
        version=1,
        parent_artifact_id=prd_v1.id,
        verification_status=ArtifactVerificationStatus.VERIFIED,
    )
    db_session.add(arch_v1)
    await db_session.flush()

    # 3. New version of PRD: PRD v2 (supersedes PRD v1)
    prd_v2 = Artifact(
        project_id=project.id,
        name="prd.md",
        file_path="artifacts/prd_v2.md",
        artifact_type=ArtifactType.PRD,
        mime_type="text/markdown",
        file_size_bytes=5100,
        version=2,
        verification_status=ArtifactVerificationStatus.VERIFIED,
    )
    db_session.add(prd_v2)
    await db_session.flush()

    # Link supersession
    prd_v1.superseded_by_id = prd_v2.id
    await db_session.commit()

    # Query back and verify lineage links
    stmt = select(Artifact).where(Artifact.id == arch_v1.id)
    reloaded_arch = (await db_session.execute(stmt)).scalar_one()

    assert reloaded_arch.parent_artifact is not None
    assert reloaded_arch.parent_artifact.id == prd_v1.id
    assert reloaded_arch.parent_artifact.name == "prd.md"

    # Verify supersession on PRD v1
    reloaded_prd1 = (
        await db_session.execute(select(Artifact).where(Artifact.id == prd_v1.id))
    ).scalar_one()
    assert reloaded_prd1.superseded_by is not None
    assert reloaded_prd1.superseded_by.id == prd_v2.id
    assert reloaded_prd1.superseded_by.version == 2


@pytest.mark.asyncio
async def test_artifact_self_referential_constraints(db_session: AsyncSession):
    """Verifies check constraints preventing self-parenting and self-supersession."""
    workspace = create_workspace("Artifact Constraint Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Artifact Constraint Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    fixed_id = uuid.uuid4()
    # 1. Self-parenting attempt
    self_parent = Artifact(
        id=fixed_id,
        project_id=project.id,
        name="recursive.md",
        file_path="artifacts/recursive.md",
        artifact_type=ArtifactType.OTHER,
        mime_type="text/plain",
        file_size_bytes=100,
        parent_artifact_id=fixed_id,  # Violates ck_artifacts_no_self_parent
    )
    db_session.add(self_parent)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Version < 1 attempt
    invalid_ver = Artifact(
        project_id=project.id,
        name="zero_version.md",
        file_path="artifacts/zero_version.md",
        artifact_type=ArtifactType.OTHER,
        mime_type="text/plain",
        file_size_bytes=100,
        version=0,  # Violates ck_artifacts_version_positive
    )
    db_session.add(invalid_ver)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 3. Self-supersession attempt
    self_super = Artifact(
        id=fixed_id,
        project_id=project.id,
        name="self_super.md",
        file_path="artifacts/self_super.md",
        artifact_type=ArtifactType.OTHER,
        mime_type="text/plain",
        file_size_bytes=100,
        superseded_by_id=fixed_id,  # Violates ck_artifacts_no_self_supersede
    )
    db_session.add(self_super)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_project_memory_self_referential_constraints(db_session: AsyncSession):
    """Verifies check constraints preventing self-referencing revisions and conflicts."""
    workspace = create_workspace("Self Ref Workspace")
    db_session.add(workspace)
    await db_session.flush()

    project = create_project("Self Ref Project", workspace.id, StudioType.SAAS)
    db_session.add(project)
    await db_session.flush()

    fixed_id = uuid.uuid4()
    # 1. Self-revision attempt
    self_rev = ProjectMemory(
        id=fixed_id,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Self Revision Attempt",
        content="Violates ck_project_memories_no_self_revision",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.0,
        previous_revision_id=fixed_id,
    )
    db_session.add(self_rev)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Self-conflict attempt
    self_conflict = ProjectMemory(
        id=fixed_id,
        project_id=project.id,
        category=MemoryCategory.DECISION,
        summary="Self Conflict Attempt",
        content="Violates ck_project_memories_no_self_conflict",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.0,
        conflicting_memory_id=fixed_id,
    )
    db_session.add(self_conflict)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_project_isolation_and_cascade_delete(db_session: AsyncSession):
    """Verifies that project memories are isolated and cascade-deleted when project is removed."""
    workspace = create_workspace("Isolation Workspace")
    db_session.add(workspace)
    await db_session.flush()

    proj_a = create_project("Project Alpha", workspace.id, StudioType.SAAS)
    proj_b = create_project("Project Beta", workspace.id, StudioType.MEDIA)
    db_session.add_all([proj_a, proj_b])
    await db_session.flush()

    mem_a = ProjectMemory(
        project_id=proj_a.id,
        category=MemoryCategory.GOAL
        if hasattr(MemoryCategory, "GOAL")
        else MemoryCategory.OBJECTIVE,
        summary="Alpha Core Vision",
        content="Alpha confidential vision details.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.0,
        is_verified=True,
    )
    mem_b = ProjectMemory(
        project_id=proj_b.id,
        category=MemoryCategory.OBJECTIVE,
        summary="Beta Video Series",
        content="Beta public media campaign outline.",
        provenance_type=MemoryProvenanceType.USER_PROVIDED,
        confidence_score=1.0,
        is_verified=True,
    )
    db_session.add_all([mem_a, mem_b])
    await db_session.commit()

    # Verify isolation
    res_a = await db_session.execute(
        select(ProjectMemory).where(ProjectMemory.project_id == proj_a.id)
    )
    mems_a = list(res_a.scalars().all())
    assert len(mems_a) == 1
    assert mems_a[0].summary == "Alpha Core Vision"

    res_b = await db_session.execute(
        select(ProjectMemory).where(ProjectMemory.project_id == proj_b.id)
    )
    mems_b = list(res_b.scalars().all())
    assert len(mems_b) == 1
    assert mems_b[0].summary == "Beta Video Series"

    # Verify Cascade Delete: deleting Project Alpha must remove its memories
    await db_session.delete(proj_a)
    await db_session.commit()

    res_deleted = await db_session.execute(
        select(ProjectMemory).where(ProjectMemory.project_id == proj_a.id)
    )
    assert len(list(res_deleted.scalars().all())) == 0

    # Project Beta memory must remain intact
    res_b_after = await db_session.execute(
        select(ProjectMemory).where(ProjectMemory.project_id == proj_b.id)
    )
    assert len(list(res_b_after.scalars().all())) == 1
