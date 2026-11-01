import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.artifact import ArtifactType


class ArtifactCreate(BaseModel):
    project_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    task_id: str | None = None
    name: str
    file_path: str
    artifact_type: ArtifactType = ArtifactType.OTHER
    mime_type: str = "text/plain"
    file_size_bytes: int = 0
    metadata_json: dict[str, Any] = {}


class ArtifactRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    execution_id: uuid.UUID | None
    task_id: str | None
    name: str
    file_path: str
    artifact_type: ArtifactType
    mime_type: str
    file_size_bytes: int
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
