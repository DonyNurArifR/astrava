import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.approval import Approval
    from app.models.project import Project
    from app.models.usage import ModelExecution


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutorType(enum.StrEnum):
    CLAUDE_CODE = "claude_code"
    ANTIGRAVITY = "antigravity"
    DETERMINISTIC = "deterministic"


class Task(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    executor_type: Mapped[ExecutorType] = mapped_column(
        Enum(ExecutorType, native_enum=False),
        default=ExecutorType.CLAUDE_CODE,
        nullable=False,
    )
    assigned_model: Mapped[str] = mapped_column(
        String(100), default="claude-haiku-5-5", nullable=False
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, native_enum=False),
        default=RiskLevel.LOW,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dependency_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="task", cascade="all, delete-orphan"
    )
    model_executions: Mapped[list["ModelExecution"]] = relationship(
        "ModelExecution", back_populates="task", cascade="all, delete-orphan"
    )
