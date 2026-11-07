import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.execution import WorkflowExecution
from app.models.project import Project, ProjectStatus
from app.models.task import Task
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.workspace_service import get_or_create_default_workspace
from app.workspace.path_security import PathContainmentError, validate_ref_name, validate_repo_path


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)


class ProjectValidationError(ValueError):
    """A repository location or branch name was rejected (HTTP 422 at the API)."""


def _canonical_repo_path(raw: str) -> str:
    try:
        return str(validate_repo_path(raw))
    except PathContainmentError as exc:
        raise ProjectValidationError(str(exc)) from exc


def _checked_base_branch(raw: str) -> str:
    try:
        return validate_ref_name(raw, kind="base branch")
    except PathContainmentError as exc:
        raise ProjectValidationError(str(exc)) from exc


class ProjectService:
    @staticmethod
    async def create(db: AsyncSession, data: ProjectCreate) -> Project:
        workspace_id = data.workspace_id
        if not workspace_id:
            default_ws = await get_or_create_default_workspace(db)
            workspace_id = default_ws.id

        base_slug = slugify(data.name) or "project"
        slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        repo_path = _canonical_repo_path(data.repo_path) if data.repo_path is not None else None
        base_branch = _checked_base_branch(data.base_branch) if data.base_branch else "main"

        project = Project(
            workspace_id=workspace_id,
            name=data.name,
            slug=slug,
            description=data.description,
            studio_type=data.studio_type,
            status=ProjectStatus.ACTIVE,
            target_objectives=data.target_objectives,
            settings_json=data.settings_json,
            repo_path=repo_path,
            base_branch=base_branch,
        )
        db.add(project)
        await db.flush()
        await db.refresh(project)
        return project

    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: uuid.UUID) -> Project | None:
        stmt = select(Project).where(Project.id == project_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_all(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: ProjectStatus | None = None,
        studio_type: str | None = None,
    ) -> list[Project]:
        stmt = select(Project).order_by(Project.created_at.desc())
        if status:
            stmt = stmt.where(Project.status == status)
        if studio_type:
            stmt = stmt.where(Project.studio_type == studio_type)
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession, project_id: uuid.UUID, data: ProjectUpdate
    ) -> Project | None:
        project = await ProjectService.get_by_id(db, project_id)
        if not project:
            return None

        update_dict = data.model_dump(exclude_unset=True)
        # Validate everything before mutating the ORM object. Explicit null clears repo_path.
        if update_dict.get("repo_path") is not None:
            update_dict["repo_path"] = _canonical_repo_path(update_dict["repo_path"])
        if update_dict.get("base_branch") is not None:
            update_dict["base_branch"] = _checked_base_branch(update_dict["base_branch"])
        for key, value in update_dict.items():
            setattr(project, key, value)

        await db.flush()
        await db.refresh(project)
        return project

    @staticmethod
    async def delete(db: AsyncSession, project_id: uuid.UUID) -> bool:
        project = await ProjectService.get_by_id(db, project_id)
        if not project:
            return False
        await db.delete(project)
        await db.flush()
        return True

    @staticmethod
    async def get_stats(db: AsyncSession) -> dict[str, int]:
        total_projects = await db.scalar(select(func.count(Project.id))) or 0
        active_projects = (
            await db.scalar(
                select(func.count(Project.id)).where(Project.status == ProjectStatus.ACTIVE)
            )
            or 0
        )
        total_tasks = await db.scalar(select(func.count(Task.id))) or 0
        total_executions = await db.scalar(select(func.count(WorkflowExecution.id))) or 0
        total_artifacts = await db.scalar(select(func.count(Artifact.id))) or 0

        return {
            "total_projects": total_projects,
            "active_projects": active_projects,
            "total_tasks": total_tasks,
            "total_executions": total_executions,
            "total_artifacts": total_artifacts,
        }
