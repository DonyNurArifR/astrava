"""``worker_runs``: the control plane's durable record of every worker it asked the broker for.

The API persists each state transition (fenced by the execution epoch); the broker keeps only its
own labels and audit log. Rows survive an API crash and drive reconciliation during recovery.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class WorkerRunState(enum.StrEnum):
    """Superset of the broker's states: REQUESTED/COLLECTED/CLEANUP_FAILED are control-plane only.

    ADMITTED (budget reservation exists) is part of the target lifecycle but is introduced when
    workers are wired into dispatch (M1.5-2b+); 2a rows go REQUESTED -> CREATED directly.
    """

    REQUESTED = "requested"
    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    KILLED = "killed"
    TIMED_OUT = "timed_out"
    LOST = "lost"
    COLLECTED = "collected"
    CLEANED = "cleaned"
    CLEANUP_FAILED = "cleanup_failed"


# Forward-only progress order; CLEANUP_FAILED may be retried into CLEANED.
STATE_RANK: dict[WorkerRunState, int] = {
    WorkerRunState.REQUESTED: 0,
    WorkerRunState.CREATED: 1,
    WorkerRunState.RUNNING: 2,
    WorkerRunState.EXITED: 3,
    WorkerRunState.KILLED: 3,
    WorkerRunState.TIMED_OUT: 3,
    WorkerRunState.LOST: 3,
    WorkerRunState.COLLECTED: 4,
    WorkerRunState.CLEANUP_FAILED: 5,
    WorkerRunState.CLEANED: 6,
}
ACTIVE_STATES = frozenset(
    {WorkerRunState.REQUESTED, WorkerRunState.CREATED, WorkerRunState.RUNNING}
)
_STATE_LIST = ", ".join(f"'{s.value}'" for s in WorkerRunState)


class WorkerRun(Base, UUIDMixin, TimestampMixin):
    """``id`` is the worker_run_id used on the broker wire."""

    __tablename__ = "worker_runs"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "task_id", "attempt", "kind", name="uq_worker_runs_exec_task_attempt"
        ),
        CheckConstraint(f"state IN ({_STATE_LIST})", name="ck_worker_runs_state"),
        CheckConstraint("attempt >= 0", name="ck_worker_runs_attempt_nonneg"),
        CheckConstraint("lease_epoch >= 0", name="ck_worker_runs_epoch_nonneg"),
        Index("ix_worker_runs_exec_state", "execution_id", "state"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(40), nullable=False)
    image_alias: Mapped[str] = mapped_column(String(40), nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkerRunState.REQUESTED.value
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budget_reservations.id", ondelete="SET NULL"), nullable=True
    )
    fence_token_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wall_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False)
    image_digest: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
