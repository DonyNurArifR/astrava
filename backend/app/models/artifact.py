import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.execution import WorkflowExecution
    from app.models.project import Project


class ArtifactType(enum.StrEnum):
    PRD = "prd"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    CODE_DIFF = "code_diff"
    TEST_REPORT = "test_report"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    MEDIA_METADATA = "media_metadata"
    OTHER = "other"


class Artifact(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "artifacts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, native_enum=False),
        default=ArtifactType.OTHER,
        nullable=False,
        index=True,
    )
    mime_type: Mapped[str] = mapped_column(String(100), default="text/plain", nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="artifacts")
    execution: Mapped["WorkflowExecution | None"] = relationship(
        "WorkflowExecution", back_populates="artifacts"
    )
