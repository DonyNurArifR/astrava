"""add execution lease and run epoch (M1.5-1c)

Revision ID: b7c1d2e3f4a5
Revises: 6db676dd20fd
Create Date: 2026-11-07 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "6db676dd20fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column("run_epoch", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "workflow_executions", sa.Column("lease_owner", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "workflow_executions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "lease_expires_at")
    op.drop_column("workflow_executions", "lease_owner")
    op.drop_column("workflow_executions", "run_epoch")
