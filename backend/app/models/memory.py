import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.execution import WorkflowExecution
    from app.models.project import Project


class MemoryCategory(enum.StrEnum):
    OBJECTIVE = "objective"
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    DISCOVERY = "discovery"
    PREFERENCE = "preference"
    OPEN_QUESTION = "open_question"
    RISK = "risk"
    MILESTONE = "milestone"
    REJECTED_APPROACH = "rejected_approach"


class MemoryProvenanceType(enum.StrEnum):
    USER_PROVIDED = "user_provided"
    VERIFIED_FINDING = "verified_finding"
    AGENT_CONCLUSION = "agent_conclusion"
    ASSUMPTION = "assumption"


class MemoryStatus(enum.StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class MemoryConflictStatus(enum.StrEnum):
    NONE = "none"
    DETECTED = "detected"
    RESOLVED = "resolved"


class MemoryAuditAction(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    VERIFIED = "verified"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"


class IngestionOperationStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ProjectMemory(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "project_memories"
    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_project_memories_confidence_range",
        ),
        CheckConstraint("revision >= 1", name="ck_project_memories_revision_positive"),
        CheckConstraint(
            "previous_revision_id IS NULL OR previous_revision_id <> id",
            name="ck_project_memories_no_self_revision",
        ),
        CheckConstraint(
            "conflicting_memory_id IS NULL OR conflicting_memory_id <> id",
            name="ck_project_memories_no_self_conflict",
        ),
        Index("ix_project_memories_project_status_category", "project_id", "status", "category"),
        Index(
            "uq_project_memories_fingerprint",
            "project_id",
            "fingerprint",
            unique=True,
            # Enum columns persist member NAMES (ACTIVE/PROPOSED), not lowercase values.
            postgresql_where=text("fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')"),
        ),
        Index(
            "ix_project_memories_tsv",
            text(
                "to_tsvector('english'::regconfig, (coalesce(summary, ''::character varying)::text || ' '::text) || coalesce(content, ''::text))"
            ),
            postgresql_using="gin",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[MemoryCategory] = mapped_column(
        Enum(MemoryCategory, native_enum=False),
        nullable=False,
        index=True,
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_type: Mapped[MemoryProvenanceType] = mapped_column(
        Enum(MemoryProvenanceType, native_enum=False),
        nullable=False,
        index=True,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[MemoryStatus] = mapped_column(
        Enum(MemoryStatus, native_enum=False),
        default=MemoryStatus.PROPOSED,
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_memories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conflict_status: Mapped[MemoryConflictStatus] = mapped_column(
        Enum(MemoryConflictStatus, native_enum=False),
        default=MemoryConflictStatus.NONE,
        nullable=False,
        index=True,
    )
    conflicting_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_memories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ingestion_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_operations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project")
    execution: Mapped["WorkflowExecution | None"] = relationship("WorkflowExecution")
    source_artifact: Mapped["Artifact | None"] = relationship("Artifact")
    previous_revision: Mapped["ProjectMemory | None"] = relationship(
        "ProjectMemory",
        foreign_keys="[ProjectMemory.previous_revision_id]",
        remote_side="[ProjectMemory.id]",
    )
    conflicting_memory: Mapped["ProjectMemory | None"] = relationship(
        "ProjectMemory",
        foreign_keys="[ProjectMemory.conflicting_memory_id]",
        remote_side="[ProjectMemory.id]",
    )
    audit_logs: Mapped[list["MemoryAuditLog"]] = relationship(
        "MemoryAuditLog",
        back_populates="memory",
        passive_deletes=True,
    )


class IngestionOperation(Base, UUIDMixin, TimestampMixin):
    """Tracks one idempotent knowledge-ingestion run for a workflow execution."""

    __tablename__ = "ingestion_operations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "operation_token", name="uq_ingestion_operations_project_token"
        ),
        Index("ix_ingestion_operations_project_execution", "project_id", "execution_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    operation_token: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[IngestionOperationStatus] = mapped_column(
        Enum(IngestionOperationStatus, native_enum=False),
        default=IngestionOperationStatus.PENDING,
        server_default=IngestionOperationStatus.PENDING.name,
        nullable=False,
    )
    candidate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    ingested_memory_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default=text("'[]'"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryAuditLog(Base, UUIDMixin):
    """Append-only audit trail for project memory mutations."""

    __tablename__ = "memory_audit_logs"
    __table_args__ = (Index("ix_memory_audit_logs_project_created", "project_id", "created_at"),)

    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_memories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[MemoryAuditAction] = mapped_column(
        Enum(MemoryAuditAction, native_enum=False),
        nullable=False,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    memory: Mapped["ProjectMemory | None"] = relationship(
        "ProjectMemory", back_populates="audit_logs"
    )
    project: Mapped["Project"] = relationship("Project")
