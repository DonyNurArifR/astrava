import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, Enum, ForeignKey, Integer, String, text
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


class ArtifactVerificationStatus(enum.StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


class Artifact(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "parent_artifact_id IS NULL OR parent_artifact_id <> id",
            name="ck_artifacts_no_self_parent",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_artifacts_no_self_supersede",
        ),
        CheckConstraint("version >= 1", name="ck_artifacts_version_positive"),
    )

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
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )
    parent_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_status: Mapped[ArtifactVerificationStatus] = mapped_column(
        Enum(ArtifactVerificationStatus, native_enum=False),
        default=ArtifactVerificationStatus.UNVERIFIED,
        nullable=False,
        index=True,
    )
    verification_details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="artifacts")
    execution: Mapped["WorkflowExecution | None"] = relationship(
        "WorkflowExecution", back_populates="artifacts"
    )
    parent_artifact: Mapped["Artifact | None"] = relationship(
        "Artifact",
        foreign_keys="[Artifact.parent_artifact_id]",
        remote_side="[Artifact.id]",
    )
    superseded_by: Mapped["Artifact | None"] = relationship(
        "Artifact",
        foreign_keys="[Artifact.superseded_by_id]",
        remote_side="[Artifact.id]",
    )
