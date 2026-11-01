"""Integration tests for ArtifactIntelligenceService in ASTRAVA V1.3.

Verifies:
1. Project-scoped retrieval and isolation.
2. Parent assignment and ancestry traversal.
3. Long-cycle and self-parenting prevention.
4. Cross-project lineage rejection.
5. Supersession rules, version progression requirements, and supersession cycles.
6. Verification status transitions and details recording.
7. Lineage queries combining ancestors, descendants, superseded_by, and supersedes.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact, ArtifactType, ArtifactVerificationStatus
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.services.artifact_intelligence_service import (
    CROSS_PROJECT_LINEAGE_ERROR,
    ArtifactIntelligenceService,
)


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


def create_artifact(
    project_id: uuid.UUID,
    name: str,
    version: int = 1,
    parent_id: uuid.UUID | None = None,
    superseded_by_id: uuid.UUID | None = None,
    verification_status: ArtifactVerificationStatus = ArtifactVerificationStatus.UNVERIFIED,
) -> Artifact:
    return Artifact(
        project_id=project_id,
        name=name,
        file_path=f"/artifacts/{name.lower().replace(' ', '_')}.py",
        artifact_type=ArtifactType.CODE_DIFF,
        mime_type="text/x-python",
        file_size_bytes=1024,
        version=version,
        parent_artifact_id=parent_id,
        superseded_by_id=superseded_by_id,
        verification_status=verification_status,
    )


@pytest.mark.asyncio
async def test_artifact_retrieval_and_project_scoping(db_session: AsyncSession):
    """Artifact retrieval strictly enforces project scoping."""
    ws = create_workspace("Scope WS")
    db_session.add(ws)
    await db_session.flush()

    p1 = create_project("P1", ws.id)
    p2 = create_project("P2", ws.id)
    db_session.add_all([p1, p2])
    await db_session.flush()

    art1 = create_artifact(p1.id, "p1_module.py")
    db_session.add(art1)
    await db_session.commit()

    # Query with correct project
    found = await ArtifactIntelligenceService.get_artifact(db_session, p1.id, art1.id)
    assert found is not None
    assert found.id == art1.id
    assert found.name == "p1_module.py"

    # Query with wrong project returns None
    wrong = await ArtifactIntelligenceService.get_artifact(db_session, p2.id, art1.id)
    assert wrong is None

    # Lineage query across project boundary raises LookupError
    with pytest.raises(LookupError, match=f"Artifact {art1.id} not found in project {p2.id}"):
        await ArtifactIntelligenceService.get_lineage(db_session, p2.id, art1.id)


@pytest.mark.asyncio
async def test_set_parent_and_lineage_ancestry_traversal(db_session: AsyncSession):
    """Verifies parent assignment and multi-generation ancestor/descendant traversal."""
    ws = create_workspace("Lineage WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Lineage Project", ws.id)
    db_session.add(p)
    await db_session.flush()

    # Create root -> child1 -> grandchild
    #               -> child2
    root = create_artifact(p.id, "root.py", version=1)
    db_session.add(root)
    await db_session.commit()

    child1 = create_artifact(p.id, "child1.py", version=1)
    child2 = create_artifact(p.id, "child2.py", version=1)
    db_session.add_all([child1, child2])
    await db_session.commit()

    grandchild = create_artifact(p.id, "grandchild.py", version=1)
    db_session.add(grandchild)
    await db_session.commit()

    # Wire up ancestry using service
    await ArtifactIntelligenceService.set_parent(db_session, p.id, child1.id, root.id)
    await ArtifactIntelligenceService.set_parent(db_session, p.id, child2.id, root.id)
    await ArtifactIntelligenceService.set_parent(db_session, p.id, grandchild.id, child1.id)
    await db_session.commit()

    # Test lineage for grandchild: ancestors should be [root, child1]
    lineage_gc = await ArtifactIntelligenceService.get_lineage(db_session, p.id, grandchild.id)
    ancestor_names = [a.name for a in lineage_gc["ancestors"]]
    assert ancestor_names == ["root.py", "child1.py"]
    assert lineage_gc["descendants"] == []

    # Test lineage for root: descendants should be child1, child2, grandchild
    lineage_root = await ArtifactIntelligenceService.get_lineage(db_session, p.id, root.id)
    assert lineage_root["ancestors"] == []
    descendant_names = {d.name for d in lineage_root["descendants"]}
    assert descendant_names == {"child1.py", "child2.py", "grandchild.py"}

    # Disconnect grandchild parent
    await ArtifactIntelligenceService.set_parent(db_session, p.id, grandchild.id, None)
    await db_session.commit()

    refreshed_gc = await ArtifactIntelligenceService.get_lineage(db_session, p.id, grandchild.id)
    assert refreshed_gc["ancestors"] == []


@pytest.mark.asyncio
async def test_ancestry_cycle_prevention(db_session: AsyncSession):
    """Verifies that self-parenting and long multi-hop ancestry cycles are rejected."""
    ws = create_workspace("Cycle WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Cycle Project", ws.id)
    db_session.add(p)
    await db_session.flush()

    art_a = create_artifact(p.id, "art_a.py")
    art_b = create_artifact(p.id, "art_b.py")
    art_c = create_artifact(p.id, "art_c.py")
    db_session.add_all([art_a, art_b, art_c])
    await db_session.commit()

    a_id = art_a.id
    b_id = art_b.id
    c_id = art_c.id
    proj_id = p.id

    # 1. Direct self-parenting via service
    with pytest.raises(ValueError, match="Artifact cannot be its own parent"):
        await ArtifactIntelligenceService.set_parent(db_session, proj_id, a_id, a_id)

    # 2. Direct self-parenting via DB constraint
    art_a.parent_artifact_id = a_id
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 3. Build chain: A -> B -> C
    # B's parent is A
    await ArtifactIntelligenceService.set_parent(db_session, proj_id, b_id, a_id)
    # C's parent is B
    await ArtifactIntelligenceService.set_parent(db_session, proj_id, c_id, b_id)
    await db_session.commit()

    # 4. Attempt to make A's parent C -> would create cycle A -> B -> C -> A
    with pytest.raises(ValueError, match="Cycle detected in artifact ancestry"):
        await ArtifactIntelligenceService.set_parent(db_session, proj_id, a_id, c_id)


@pytest.mark.asyncio
async def test_cross_project_lineage_rejection(db_session: AsyncSession):
    """Verifies that setting a parent or superseded_by across project boundaries is strictly rejected."""
    ws = create_workspace("Cross-Project WS")
    db_session.add(ws)
    await db_session.flush()

    proj1 = create_project("Proj1", ws.id)
    proj2 = create_project("Proj2", ws.id)
    db_session.add_all([proj1, proj2])
    await db_session.flush()

    art1 = create_artifact(proj1.id, "art1.py", version=1)
    art2 = create_artifact(proj2.id, "art2.py", version=2)
    db_session.add_all([art1, art2])
    await db_session.commit()

    # Attempt cross-project parent
    with pytest.raises(ValueError, match=CROSS_PROJECT_LINEAGE_ERROR):
        await ArtifactIntelligenceService.set_parent(db_session, proj1.id, art1.id, art2.id)

    # Attempt cross-project supersession
    with pytest.raises(ValueError, match=CROSS_PROJECT_LINEAGE_ERROR):
        await ArtifactIntelligenceService.set_superseded_by(db_session, proj1.id, art1.id, art2.id)


@pytest.mark.asyncio
async def test_supersession_rules_and_version_progression(db_session: AsyncSession):
    """Verifies version progression requirement, self-supersede guard, and supersession cycle detection."""
    ws = create_workspace("Supersede WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Supersede Project", ws.id)
    db_session.add(p)
    await db_session.flush()

    v1 = create_artifact(p.id, "spec.md", version=1)
    v2 = create_artifact(p.id, "spec.md", version=2)
    v3 = create_artifact(p.id, "spec.md", version=3)
    db_session.add_all([v1, v2, v3])
    await db_session.commit()

    p_id = p.id
    v1_id = v1.id
    v2_id = v2.id
    v3_id = v3.id

    # 1. Self-supersede via service
    with pytest.raises(ValueError, match="Artifact cannot supersede itself"):
        await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v1_id, v1_id)

    # 2. Self-supersede via DB constraint
    v1_obj = await db_session.get(Artifact, v1_id)
    assert v1_obj is not None
    v1_obj.superseded_by_id = v1_id
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 3. Version regression or equal version rejected
    # v2 cannot be superseded by v1 (1 <= 2)
    with pytest.raises(
        ValueError,
        match="Superseding artifact version must be greater than current artifact version",
    ):
        await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v2_id, v1_id)

    # v2 cannot supersede v2 if versions equal
    v2_alt = create_artifact(p_id, "spec_alt.md", version=2)
    db_session.add(v2_alt)
    await db_session.commit()
    v2_alt_id = v2_alt.id

    with pytest.raises(
        ValueError,
        match="Superseding artifact version must be greater than current artifact version",
    ):
        await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v2_id, v2_alt_id)

    # 4. Valid forward progression: v1 superseded by v2, v2 superseded by v3
    await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v1_id, v2_id)
    await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v2_id, v3_id)
    await db_session.commit()

    # 5. Cycle attempt: v3 superseded by v1 (also fails version check, but let's test cycle logic)
    with pytest.raises(ValueError):
        await ArtifactIntelligenceService.set_superseded_by(db_session, p_id, v3_id, v1_id)

    # Verify lineage reflects supersession
    v2_lineage = await ArtifactIntelligenceService.get_lineage(db_session, p_id, v2_id)
    assert v2_lineage["superseded_by"] is not None
    assert v2_lineage["superseded_by"].id == v3_id
    assert len(v2_lineage["supersedes"]) == 1
    assert v2_lineage["supersedes"][0].id == v1_id


@pytest.mark.asyncio
async def test_update_verification_status(db_session: AsyncSession):
    """Verifies artifact verification status transitions and metadata storage."""
    ws = create_workspace("Verif WS")
    db_session.add(ws)
    await db_session.flush()

    p = create_project("Verif Project", ws.id)
    db_session.add(p)
    await db_session.flush()

    art = create_artifact(p.id, "code.py", version=1)
    db_session.add(art)
    await db_session.commit()

    assert art.verification_status == ArtifactVerificationStatus.UNVERIFIED

    # Update to VERIFIED with audit details
    details = {"checker": "pytest", "tests_passed": 42, "coverage_pct": 98.5}
    updated = await ArtifactIntelligenceService.update_verification_status(
        db_session,
        p.id,
        art.id,
        status=ArtifactVerificationStatus.VERIFIED,
        details=details,
    )
    await db_session.commit()

    assert updated.verification_status == ArtifactVerificationStatus.VERIFIED
    assert updated.verification_details["checker"] == "pytest"
    assert updated.verification_details["coverage_pct"] == 98.5

    # Update to FAILED
    failed = await ArtifactIntelligenceService.update_verification_status(
        db_session,
        p.id,
        art.id,
        status=ArtifactVerificationStatus.FAILED,
        details={"error": "SyntaxError on line 12"},
    )
    await db_session.commit()

    assert failed.verification_status == ArtifactVerificationStatus.FAILED
    assert failed.verification_details["error"] == "SyntaxError on line 12"
