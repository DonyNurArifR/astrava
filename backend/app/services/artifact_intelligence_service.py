import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact, ArtifactVerificationStatus

CROSS_PROJECT_LINEAGE_ERROR = "Cross-project artifact lineage is prohibited"


class ArtifactIntelligenceService:
    """Lineage (parent/ancestry), supersession, and verification state for artifacts.

    All lineage operations are scoped to a single project. Walks over the lineage
    graph are guarded by visited sets and stop at project boundaries, so corrupt
    data cannot cause infinite loops or cross-project traversal.
    """

    @staticmethod
    async def get_artifact(
        db: AsyncSession, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Artifact | None:
        stmt = select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.project_id == project_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _require_artifact(
        db: AsyncSession, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Artifact:
        artifact = await ArtifactIntelligenceService.get_artifact(db, project_id, artifact_id)
        if artifact is None:
            raise LookupError(f"Artifact {artifact_id} not found in project {project_id}")
        return artifact

    @staticmethod
    async def _walk_parents(
        db: AsyncSession,
        project_id: uuid.UUID,
        start_id: uuid.UUID | None,
    ) -> list[Artifact]:
        """Returns the parent chain starting at start_id (nearest ancestor first)."""
        chain: list[Artifact] = []
        seen: set[uuid.UUID] = set()
        current_id = start_id
        while current_id is not None and current_id not in seen:
            seen.add(current_id)
            node = await db.get(Artifact, current_id)
            if node is None or node.project_id != project_id:
                break
            chain.append(node)
            current_id = node.parent_artifact_id
        return chain

    @staticmethod
    async def _walk_supersession(
        db: AsyncSession,
        project_id: uuid.UUID,
        start_id: uuid.UUID | None,
    ) -> list[Artifact]:
        """Returns the supersession chain starting at start_id (successor first)."""
        chain: list[Artifact] = []
        seen: set[uuid.UUID] = set()
        current_id = start_id
        while current_id is not None and current_id not in seen:
            seen.add(current_id)
            node = await db.get(Artifact, current_id)
            if node is None or node.project_id != project_id:
                break
            chain.append(node)
            current_id = node.superseded_by_id
        return chain

    @staticmethod
    async def set_parent(
        db: AsyncSession,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        parent_artifact_id: uuid.UUID | None,
    ) -> Artifact:
        artifact = await ArtifactIntelligenceService._require_artifact(db, project_id, artifact_id)

        if parent_artifact_id is not None:
            if artifact_id == parent_artifact_id:
                raise ValueError("Artifact cannot be its own parent")

            parent = await db.get(Artifact, parent_artifact_id)
            if parent is None:
                raise LookupError(f"Parent artifact {parent_artifact_id} not found")
            if parent.project_id != project_id:
                raise ValueError(CROSS_PROJECT_LINEAGE_ERROR)

            # Walk parent's ancestry; if we meet artifact_id, assigning would close a loop.
            ancestry = await ArtifactIntelligenceService._walk_parents(
                db, project_id, parent_artifact_id
            )
            if any(node.id == artifact_id for node in ancestry):
                raise ValueError("Cycle detected in artifact ancestry")

        artifact.parent_artifact_id = parent_artifact_id
        await db.flush()
        await db.refresh(artifact)
        return artifact

    @staticmethod
    async def set_superseded_by(
        db: AsyncSession,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        superseded_by_id: uuid.UUID | None,
    ) -> Artifact:
        artifact = await ArtifactIntelligenceService._require_artifact(db, project_id, artifact_id)

        if superseded_by_id is not None:
            if artifact_id == superseded_by_id:
                raise ValueError("Artifact cannot supersede itself")

            target = await db.get(Artifact, superseded_by_id)
            if target is None:
                raise LookupError(f"Superseding artifact {superseded_by_id} not found")
            if target.project_id != project_id:
                raise ValueError(CROSS_PROJECT_LINEAGE_ERROR)

            # Walk target's supersession chain; if we meet artifact_id, the chain would loop.
            chain = await ArtifactIntelligenceService._walk_supersession(
                db, project_id, superseded_by_id
            )
            if any(node.id == artifact_id for node in chain):
                raise ValueError("Cycle detected in supersession chain")

            if target.version <= artifact.version:
                raise ValueError(
                    "Superseding artifact version must be greater than current artifact version"
                )

        artifact.superseded_by_id = superseded_by_id
        await db.flush()
        await db.refresh(artifact)
        return artifact

    @staticmethod
    async def get_lineage(
        db: AsyncSession, project_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> dict[str, Any]:
        artifact = await ArtifactIntelligenceService._require_artifact(db, project_id, artifact_id)

        # Ancestors: nearest-first from the walk, reversed to oldest-to-newest.
        ancestry = await ArtifactIntelligenceService._walk_parents(
            db, project_id, artifact.parent_artifact_id
        )
        ancestors = [node for node in reversed(ancestry) if node.id != artifact.id]

        # Descendants: breadth-first over children within the project.
        descendants: list[Artifact] = []
        seen: set[uuid.UUID] = {artifact.id}
        frontier: list[uuid.UUID] = [artifact.id]
        while frontier:
            stmt = select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.parent_artifact_id.in_(frontier),
            )
            result = await db.execute(stmt)
            frontier = []
            for child in result.scalars().all():
                if child.id in seen:
                    continue
                seen.add(child.id)
                descendants.append(child)
                frontier.append(child.id)

        superseded_by: Artifact | None = None
        if artifact.superseded_by_id is not None:
            superseded_by = await ArtifactIntelligenceService.get_artifact(
                db, project_id, artifact.superseded_by_id
            )

        supersedes_stmt = (
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.superseded_by_id == artifact.id,
            )
            .order_by(Artifact.version.asc())
        )
        supersedes_result = await db.execute(supersedes_stmt)
        supersedes = [node for node in supersedes_result.scalars().all() if node.id != artifact.id]

        return {
            "artifact": artifact,
            "ancestors": ancestors,
            "descendants": descendants,
            "superseded_by": superseded_by,
            "supersedes": supersedes,
        }

    @staticmethod
    async def update_verification_status(
        db: AsyncSession,
        project_id: uuid.UUID,
        artifact_id: uuid.UUID,
        status: ArtifactVerificationStatus | str,
        details: dict[str, Any] | None = None,
    ) -> Artifact:
        artifact = await ArtifactIntelligenceService._require_artifact(db, project_id, artifact_id)

        artifact.verification_status = ArtifactVerificationStatus(status)
        artifact.verification_details = dict(details) if details is not None else {}
        await db.flush()
        await db.refresh(artifact)
        return artifact
