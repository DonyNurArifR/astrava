import hashlib
import uuid
from collections.abc import Collection
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.artifact import Artifact, ArtifactType
from app.models.execution import WorkflowExecution
from app.models.project import Project
from app.schemas.artifact import ArtifactCreate
from app.workspace.path_security import (
    PathContainmentError,
    safe_join,
    write_bytes_contained,
    write_text_contained,
)

MAX_HASH_BYTES = 25 * 1024 * 1024
ArtifactSource = Literal["api", "orchestrator"]


class ArtifactNotFoundError(Exception):
    """A referenced project or execution does not exist (HTTP 404)."""


class ArtifactOwnershipError(Exception):
    """A referenced entity exists but does not own the artifact being registered (HTTP 403)."""


def _storage_root() -> Path:
    return settings.ARTIFACT_STORAGE_PATH.resolve()


def _sha256_if_small(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_HASH_BYTES:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _execution_task_ids(execution: WorkflowExecution) -> set[str]:
    tasks = (execution.state_data or {}).get("tasks") or []
    return {
        str(task["task_id"]) for task in tasks if isinstance(task, dict) and task.get("task_id")
    }


class ArtifactService:
    @staticmethod
    def sanitize_path(file_path: str) -> Path:
        """Canonical, symlink-safe path strictly inside the artifact storage directory.

        Raises PathContainmentError (a ValueError, mapped to HTTP 400) on any violation.
        """
        try:
            return safe_join(_storage_root(), file_path)
        except PathContainmentError as exc:
            raise PathContainmentError(
                f"Path traversal detected: invalid artifact path ({exc})"
            ) from exc

    @staticmethod
    def servable_path(file_path: str) -> Path | None:
        """Path for preview/download, or None unless it is a regular file (not a symlink)."""
        try:
            safe = ArtifactService.sanitize_path(file_path)
        except ValueError:
            return None
        if (_storage_root() / file_path).is_symlink() or not safe.is_file():
            return None
        return safe

    @staticmethod
    async def get_by_execution_and_path(
        db: AsyncSession, execution_id: uuid.UUID, file_path: str
    ) -> Artifact | None:
        """Finds existing artifact by execution_id and file_path."""
        safe_rel_path = str(ArtifactService.sanitize_path(file_path).relative_to(_storage_root()))
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
        *,
        source: ArtifactSource = "api",
        registered_by: str | None = None,
        known_task_ids: Collection[str] | None = None,
        producing_agent_slug: str | None = None,
        observed_sha256: str | None = None,
        location: str = "storage",
    ) -> Artifact:
        """Register an artifact after checking ownership, containment and provenance.

        ``observed_sha256`` and ``location="worktree"`` are honored only for
        ``source="orchestrator"``: the runner hashes the file inside the execution worktree and
        records that hash, so provenance describes the file the agent actually produced.
        API registrations always describe the file on disk under the project directory.

        Ownership: the project must exist; a given execution must exist and belong to the
        project; a task_id needs an execution and must be one of its task keys (or, for
        orchestrator callers only, one of ``known_task_ids``); file_path must lie inside
        this project's artifact directory. Client-supplied ``provenance`` is discarded and
        replaced with server-written provenance.
        """
        project = await db.get(Project, data.project_id)
        if project is None:
            raise ArtifactNotFoundError("Project not found")

        execution: WorkflowExecution | None = None
        if data.execution_id is not None:
            execution = await db.get(WorkflowExecution, data.execution_id)
            if execution is None:
                raise ArtifactNotFoundError("Execution not found")
            if execution.project_id != data.project_id:
                raise ArtifactOwnershipError("Execution does not belong to this project")

        if data.task_id is not None:
            if execution is None:
                raise ArtifactOwnershipError("task_id requires an execution_id")
            allowed = _execution_task_ids(execution)
            if source == "orchestrator" and known_task_ids:
                allowed |= {str(task_id) for task_id in known_task_ids}
            if data.task_id not in allowed:
                raise ArtifactOwnershipError("task_id does not belong to this execution")

        base = _storage_root()
        safe_path = ArtifactService.sanitize_path(data.file_path)
        if (base / data.file_path).is_symlink():
            raise PathContainmentError("Artifact file must not be a symbolic link")
        project_dir = (base / str(data.project_id)).resolve()
        if safe_path == project_dir or not safe_path.is_relative_to(project_dir):
            raise ArtifactOwnershipError(
                "file_path must lie inside this project's artifact directory"
            )

        rel_path = str(safe_path.relative_to(base))

        size_bytes = data.file_size_bytes
        if content is not None:
            if isinstance(content, str):
                write_text_contained(base, rel_path, content)
                size_bytes = len(content.encode("utf-8"))
            else:
                write_bytes_contained(base, rel_path, content)
                size_bytes = len(content)
        elif source == "api" or safe_path.exists():
            # API registrations must point at a real file; size and hash come from disk only.
            if not safe_path.is_file():
                if not safe_path.exists():
                    raise PathContainmentError("Artifact file does not exist")
                raise PathContainmentError("Artifact path is not a regular file")
            size_bytes = safe_path.stat().st_size

        if location not in ("storage", "worktree"):
            raise ValueError("Unknown artifact location")
        worktree_observed = source == "orchestrator" and location == "worktree"
        provenance: dict[str, Any] = {
            "source": source,
            "registered_by": registered_by
            or ("orchestrator" if source == "orchestrator" else "unknown"),
            "sha256": observed_sha256 if worktree_observed else _sha256_if_small(safe_path),
            "size_bytes": size_bytes,
            "location": "worktree" if worktree_observed else "storage",
        }
        if source == "orchestrator" and producing_agent_slug:
            provenance["producing_agent_slug"] = producing_agent_slug
        metadata = {
            key: value for key, value in (data.metadata_json or {}).items() if key != "provenance"
        }
        metadata["provenance"] = provenance

        # Deduplication check: if artifact exists for execution and path, update and return it
        if data.execution_id:
            existing = await ArtifactService.get_by_execution_and_path(
                db, data.execution_id, data.file_path
            )
            if existing:
                existing.file_size_bytes = size_bytes
                existing.name = data.name
                existing.metadata_json = metadata
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
            metadata_json=metadata,
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
        safe_path = ArtifactService.servable_path(artifact.file_path)
        if safe_path is None:
            return None
        try:
            return safe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "[Binary Content]"
