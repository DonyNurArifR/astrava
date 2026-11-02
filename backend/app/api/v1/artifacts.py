import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.artifact import ArtifactType
from app.schemas.artifact import ArtifactCreate, ArtifactRead
from app.schemas.lineage import ArtifactLineageResponse
from app.services.artifact_intelligence_service import ArtifactIntelligenceService
from app.services.artifact_service import ArtifactService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])
project_artifacts_router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["Artifacts"])


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


@project_artifacts_router.get("/{artifact_id}/lineage", response_model=ArtifactLineageResponse)
async def get_project_artifact_lineage(
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ArtifactLineageResponse:
    """Retrieve full lineage and ancestry graph for an artifact within a project."""
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    artifact = await ArtifactIntelligenceService.get_artifact(db, project_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found in project")

    lineage_data = await ArtifactIntelligenceService.get_lineage(db, project_id, artifact_id)

    parent_node = None
    if artifact.parent_artifact_id is not None:
        parent_node = await ArtifactIntelligenceService.get_artifact(
            db, project_id, artifact.parent_artifact_id
        )

    return ArtifactLineageResponse(
        artifact=ArtifactRead.model_validate(lineage_data["artifact"]),
        parent=ArtifactRead.model_validate(parent_node) if parent_node else None,
        ancestors=[ArtifactRead.model_validate(a) for a in lineage_data["ancestors"]],
        descendants=[ArtifactRead.model_validate(d) for d in lineage_data["descendants"]],
        superseded_by=ArtifactRead.model_validate(lineage_data["superseded_by"])
        if lineage_data.get("superseded_by")
        else None,
        supersedes=[ArtifactRead.model_validate(s) for s in lineage_data.get("supersedes", [])],
    )
