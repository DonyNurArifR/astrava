import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.artifact import Artifact, ArtifactType
from app.schemas.artifact import ArtifactCreate


class ArtifactService:
    @staticmethod
    def sanitize_path(file_path: str) -> Path:
        """Enforces that file_path resolves strictly within the allowed artifact storage directory."""
        base_dir = settings.ARTIFACT_STORAGE_PATH.resolve()
        target_path = (base_dir / file_path).resolve()
        if not str(target_path).startswith(str(base_dir)):
            raise ValueError(f"Path traversal detected: {file_path} is outside {base_dir}")
        return target_path

    @staticmethod
    async def get_by_execution_and_path(
        db: AsyncSession, execution_id: uuid.UUID, file_path: str
    ) -> Artifact | None:
        """Finds existing artifact by execution_id and file_path."""
        safe_rel_path = str(
            ArtifactService.sanitize_path(file_path).relative_to(
                settings.ARTIFACT_STORAGE_PATH.resolve()
            )
        )
        stmt = select(Artifact).where(
            Artifact.execution_id == execution_id,
            Artifact.file_path == safe_rel_path,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def register_artifact(
        db: AsyncSession,
        data: ArtifactCreate,
        content: str | bytes | None = None,
    ) -> Artifact:
        safe_path = ArtifactService.sanitize_path(data.file_path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        size_bytes = data.file_size_bytes
        if content is not None:
            if isinstance(content, str):
                safe_path.write_text(content, encoding="utf-8")
                size_bytes = len(content.encode("utf-8"))
            else:
                safe_path.write_bytes(content)
                size_bytes = len(content)
        elif safe_path.exists():
            size_bytes = safe_path.stat().st_size

        rel_path = str(safe_path.relative_to(settings.ARTIFACT_STORAGE_PATH.resolve()))

        # Deduplication check: if artifact exists for execution and path, update and return it
        if data.execution_id:
            existing = await ArtifactService.get_by_execution_and_path(
                db, data.execution_id, data.file_path
            )
            if existing:
                existing.file_size_bytes = size_bytes
                existing.name = data.name
                existing.metadata_json = data.metadata_json
                await db.flush()
                await db.refresh(existing)
                return existing

        artifact = Artifact(
            project_id=data.project_id,
            execution_id=data.execution_id,
            task_id=data.task_id,
            name=data.name,
            file_path=rel_path,
            artifact_type=data.artifact_type,
            mime_type=data.mime_type,
            file_size_bytes=size_bytes,
            metadata_json=data.metadata_json,
        )
        db.add(artifact)
        await db.flush()
        await db.refresh(artifact)
        return artifact

    @staticmethod
    async def get_by_id(db: AsyncSession, artifact_id: uuid.UUID) -> Artifact | None:
        stmt = select(Artifact).where(Artifact.id == artifact_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_project(
        db: AsyncSession, project_id: uuid.UUID, artifact_type: ArtifactType | None = None
    ) -> list[Artifact]:
        stmt = (
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
        )
        if artifact_type:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def read_artifact_content(artifact: Artifact) -> str | None:
        safe_path = ArtifactService.sanitize_path(artifact.file_path)
        if safe_path.exists() and safe_path.is_file():
            try:
                return safe_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return "[Binary Content]"
        return None
