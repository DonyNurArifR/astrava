import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.artifact import ArtifactType
from app.schemas.artifact import ArtifactCreate, ArtifactRead
from app.services.artifact_service import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


@router.post("", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
async def register_artifact(
    data: ArtifactCreate,
    db: AsyncSession = Depends(get_db),
) -> ArtifactRead:
    try:
        artifact = await ArtifactService.register_artifact(db, data)
        return ArtifactRead.model_validate(artifact)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/project/{project_id}", response_model=list[ArtifactRead])
async def list_project_artifacts(
    project_id: uuid.UUID,
    artifact_type: ArtifactType | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ArtifactRead]:
    artifacts = await ArtifactService.list_by_project(db, project_id, artifact_type=artifact_type)
    return [ArtifactRead.model_validate(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ArtifactRead:
    artifact = await ArtifactService.get_by_id(db, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactRead.model_validate(artifact)


@router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    artifact = await ArtifactService.get_by_id(db, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = await ArtifactService.read_artifact_content(artifact)
    if content is None:
        raise HTTPException(status_code=404, detail="Artifact file content not found")

    return PlainTextResponse(content=content, media_type=artifact.mime_type)


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    artifact = await ArtifactService.get_by_id(db, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    safe_path = ArtifactService.sanitize_path(artifact.file_path)
    if not safe_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")

    return FileResponse(
        path=safe_path,
        filename=artifact.name,
        media_type=artifact.mime_type,
    )
