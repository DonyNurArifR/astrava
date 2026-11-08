"""add worker_runs (M1.5-2a)

Revision ID: c8a1f3d5e7b9
Revises: b7c1d2e3f4a5
Create Date: 2026-11-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8a1f3d5e7b9"
down_revision: str | Sequence[str] | None = "b7c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES = (
    "requested",
    "created",
    "running",
    "exited",
    "killed",
    "timed_out",
    "lost",
    "collected",
    "cleaned",
    "cleanup_failed",
)


def upgrade() -> None:
    op.create_table(
        "worker_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=40), nullable=False),
        sa.Column("image_alias", sa.String(length=40), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_reservations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("fence_token_sha256", sa.String(length=64), nullable=True),
        sa.Column("wall_timeout_s", sa.Integer(), nullable=False),
        sa.Column("image_digest", sa.String(length=100), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "execution_id", "task_id", "attempt", "kind", name="uq_worker_runs_exec_task_attempt"
        ),
        sa.CheckConstraint(
            "state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")", name="ck_worker_runs_state"
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_worker_runs_attempt_nonneg"),
        sa.CheckConstraint("lease_epoch >= 0", name="ck_worker_runs_epoch_nonneg"),
    )
    op.create_index("ix_worker_runs_exec_state", "worker_runs", ["execution_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_worker_runs_exec_state", table_name="worker_runs")
    op.drop_table("worker_runs")
