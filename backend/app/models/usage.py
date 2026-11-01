import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.execution import WorkflowExecution
    from app.models.task import Task


class ModelExecutionStatus(enum.StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ModelExecution(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "model_executions"

    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ModelExecutionStatus] = mapped_column(
        Enum(ModelExecutionStatus, native_enum=False),
        default=ModelExecutionStatus.SUCCESS,
        nullable=False,
        index=True,
    )
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    execution: Mapped["WorkflowExecution | None"] = relationship(
        "WorkflowExecution", back_populates="model_executions"
    )
    task: Mapped["Task | None"] = relationship("Task", back_populates="model_executions")
