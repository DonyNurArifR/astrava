import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkspaceBase(BaseModel):
    name: str
    slug: str
    description: str | None = None
    settings_json: dict[str, Any] = {}


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceRead(WorkspaceBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
