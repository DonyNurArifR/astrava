import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.project import ProjectStatus
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService
from app.workspace import RepoScanner

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project = await ProjectService.create(db, data)
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: ProjectStatus | None = None,
    studio_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRead]:
    projects = await ProjectService.list_all(
        db, skip=skip, limit=limit, status=status, studio_type=studio_type
    )
    return [ProjectRead.model_validate(p) for p in projects]


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    return await ProjectService.get_stats(db)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project = await ProjectService.update(db, project_id, data)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    success = await ProjectService.delete(db, project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return None


@router.get("/{project_id}/scan")
async def scan_project_repo(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.repo_path:
        raise HTTPException(status_code=400, detail="Project does not have a repo_path configured")
    try:
        scan_result = RepoScanner.scan(project.repo_path)
        return scan_result.to_dict()
    except (FileNotFoundError, NotADirectoryError) as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to scan repository: {err}") from err
