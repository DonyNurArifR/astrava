import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.execution import WorkflowExecution
    from app.models.project import Project


class BudgetStatus(enum.StrEnum):
    ACTIVE = "active"
    WARNING = "warning"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BudgetReservationStatus(enum.StrEnum):
    ACTIVE = "active"
    RECONCILED = "reconciled"
    RELEASED = "released"
    EXPIRED = "expired"


class ExecutionBudget(Base, UUIDMixin, TimestampMixin):
    """Per-execution resource budget: hard limits, consumption counters, and open reservations."""

    __tablename__ = "execution_budgets"
    __table_args__ = (
        CheckConstraint(
            "max_cost_usd IS NULL OR max_cost_usd >= 0", name="ck_execution_budgets_max_cost_nonneg"
        ),
        CheckConstraint(
            "max_input_tokens IS NULL OR max_input_tokens >= 0",
            name="ck_execution_budgets_max_input_tokens_nonneg",
        ),
        CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens >= 0",
            name="ck_execution_budgets_max_output_tokens_nonneg",
        ),
        CheckConstraint(
            "max_total_tokens IS NULL OR max_total_tokens >= 0",
            name="ck_execution_budgets_max_total_tokens_nonneg",
        ),
        CheckConstraint(
            "max_agent_attempts IS NULL OR max_agent_attempts >= 0",
            name="ck_execution_budgets_max_agent_attempts_nonneg",
        ),
        CheckConstraint(
            "max_task_attempts IS NULL OR max_task_attempts >= 0",
            name="ck_execution_budgets_max_task_attempts_nonneg",
        ),
        CheckConstraint(
            "max_remediation_turns IS NULL OR max_remediation_turns >= 0",
            name="ck_execution_budgets_max_remediation_turns_nonneg",
        ),
        CheckConstraint(
            "max_replan_count IS NULL OR max_replan_count >= 0",
            name="ck_execution_budgets_max_replan_count_nonneg",
        ),
        CheckConstraint(
            "max_runtime_seconds IS NULL OR max_runtime_seconds >= 0",
            name="ck_execution_budgets_max_runtime_nonneg",
        ),
        CheckConstraint(
            "consumed_actual_cost_usd >= 0 AND consumed_estimated_cost_usd >= 0",
            name="ck_execution_budgets_consumed_cost_nonneg",
        ),
        CheckConstraint(
            "consumed_input_tokens >= 0 AND consumed_output_tokens >= 0 AND consumed_total_tokens >= 0",
            name="ck_execution_budgets_consumed_tokens_nonneg",
        ),
        CheckConstraint(
            "consumed_runtime_ms >= 0 AND total_agent_attempts >= 0 "
            "AND remediation_turns_count >= 0 AND replan_count >= 0",
            name="ck_execution_budgets_consumed_counters_nonneg",
        ),
        CheckConstraint(
            "reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 "
            "AND reserved_cost_usd >= 0 AND active_reservations_count >= 0",
            name="ck_execution_budgets_reserved_nonneg",
        ),
        Index("ix_execution_budgets_project_status", "project_id", "status"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Limits (NULL = dimension not limited)
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_agent_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_task_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_remediation_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_replan_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_runtime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Consumption (actuals reported by completed model calls, estimates for in-flight work)
    consumed_actual_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.0"), server_default=text("0"), nullable=False
    )
    consumed_estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.0"), server_default=text("0"), nullable=False
    )
    is_cost_estimated: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    consumed_input_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    consumed_output_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    consumed_total_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    consumed_runtime_ms: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    total_agent_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    remediation_turns_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    replan_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # Reservations held by in-flight work (sum over ACTIVE BudgetReservation rows)
    reserved_input_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    reserved_output_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    reserved_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.0"), server_default=text("0"), nullable=False
    )
    active_reservations_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    status: Mapped[BudgetStatus] = mapped_column(
        Enum(BudgetStatus, native_enum=False),
        default=BudgetStatus.ACTIVE,
        server_default=BudgetStatus.ACTIVE.name,
        nullable=False,
        index=True,
    )
    exhaustion_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )

    # Relationships
    execution: Mapped["WorkflowExecution"] = relationship("WorkflowExecution")
    project: Mapped["Project"] = relationship("Project")
    reservations: Mapped[list["BudgetReservation"]] = relationship(
        "BudgetReservation",
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    audit_logs: Mapped[list["BudgetAuditLog"]] = relationship(
        "BudgetAuditLog",
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BudgetAuditLog.created_at.desc()",
    )


class BudgetReservation(Base, UUIDMixin, TimestampMixin):
    """A hold on part of an ExecutionBudget for one unit of in-flight work (e.g. one agent call)."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("budget_id", "reservation_key", name="uq_budget_reservations_budget_key"),
        CheckConstraint(
            "reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 AND reserved_cost_usd >= 0",
            name="ck_budget_reservations_reserved_nonneg",
        ),
        CheckConstraint(
            "reconciled_cost_usd IS NULL OR reconciled_cost_usd >= 0",
            name="ck_budget_reservations_reconciled_cost_nonneg",
        ),
        Index("ix_budget_reservations_budget_status", "budget_id", "status"),
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the budget so reservations can be queried per execution without a join.
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reservation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reserved_input_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    reserved_output_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    reserved_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.0"), server_default=text("0"), nullable=False
    )
    reconciled_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    fence_token: Mapped[str] = mapped_column(
        String(64), nullable=False, default=lambda: uuid.uuid4().hex
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    status: Mapped[BudgetReservationStatus] = mapped_column(
        Enum(BudgetReservationStatus, native_enum=False),
        default=BudgetReservationStatus.ACTIVE,
        server_default=BudgetReservationStatus.ACTIVE.name,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )

    # Relationships
    budget: Mapped["ExecutionBudget"] = relationship(
        "ExecutionBudget", back_populates="reservations"
    )
    execution: Mapped["WorkflowExecution"] = relationship("WorkflowExecution")


class BudgetAuditLog(Base, UUIDMixin, TimestampMixin):
    """Immutable audit record for execution budget limit adjustments."""

    __tablename__ = "budget_audit_logs"
    __table_args__ = (
        Index("ix_budget_audit_logs_budget_created", "budget_id", "created_at"),
        Index("ix_budget_audit_logs_execution_created", "execution_id", "created_at"),
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(50), default="budget_increase", nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), default="operator", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_limits: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )
    new_limits: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'"), nullable=False
    )

    # Relationships
    budget: Mapped["ExecutionBudget"] = relationship("ExecutionBudget", back_populates="audit_logs")
    execution: Mapped["WorkflowExecution"] = relationship("WorkflowExecution")
