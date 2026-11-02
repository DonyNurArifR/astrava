"""Pydantic v2 schemas for artifact lineage and ancestry exploration."""

from pydantic import BaseModel, ConfigDict

from app.schemas.artifact import ArtifactRead


class ArtifactLineageResponse(BaseModel):
    """Lineage representation of an artifact with its ancestral tree and supersession links."""

    artifact: ArtifactRead
    parent: ArtifactRead | None = None
    ancestors: list[ArtifactRead] = []
    descendants: list[ArtifactRead] = []
    superseded_by: ArtifactRead | None = None
    supersedes: list[ArtifactRead] = []

    model_config = ConfigDict(from_attributes=True)
