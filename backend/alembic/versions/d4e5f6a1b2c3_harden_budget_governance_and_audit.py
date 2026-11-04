"""harden_budget_governance_and_audit

Revision ID: d4e5f6a1b2c3
Revises: 9c4d2e1f8a7b
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = '9c4d2e1f8a7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: numeric precision for monetary fields, fencing tokens, audit logging."""
    # 1. Alter execution_budgets monetary columns from Float to Numeric(12, 6)
    op.alter_column(
        'execution_budgets',
        'max_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=True,
    )
    op.alter_column(
        'execution_budgets',
        'consumed_actual_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'execution_budgets',
        'consumed_estimated_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'execution_budgets',
        'reserved_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )

    # 2. Alter budget_reservations monetary columns and add fence_token / attempt_number
    op.alter_column(
        'budget_reservations',
        'reserved_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'budget_reservations',
        'reconciled_cost_usd',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=True,
    )
    op.add_column(
        'budget_reservations',
        sa.Column('fence_token', sa.String(length=64), server_default='', nullable=False),
    )
    op.add_column(
        'budget_reservations',
        sa.Column('attempt_number', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )

    # 3. Create budget_audit_logs table
    op.create_table(
        'budget_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('budget_id', sa.UUID(), nullable=False),
        sa.Column('execution_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.String(length=100), nullable=False),
        sa.Column('actor_type', sa.String(length=50), server_default='operator', nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('previous_limits', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('new_limits', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(['budget_id'], ['execution_budgets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['execution_id'], ['workflow_executions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_budget_audit_logs_budget_created', 'budget_audit_logs', ['budget_id', 'created_at'], unique=False
    )
    op.create_index(
        'ix_budget_audit_logs_execution_created', 'budget_audit_logs', ['execution_id', 'created_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_budget_audit_logs_execution_created', table_name='budget_audit_logs')
    op.drop_index('ix_budget_audit_logs_budget_created', table_name='budget_audit_logs')
    op.drop_table('budget_audit_logs')

    op.drop_column('budget_reservations', 'attempt_number')
    op.drop_column('budget_reservations', 'fence_token')

    op.alter_column(
        'budget_reservations',
        'reconciled_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=True,
    )
    op.alter_column(
        'budget_reservations',
        'reserved_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )

    op.alter_column(
        'execution_budgets',
        'reserved_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'execution_budgets',
        'consumed_estimated_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'execution_budgets',
        'consumed_actual_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default=sa.text('0'),
    )
    op.alter_column(
        'execution_budgets',
        'max_cost_usd',
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Float(),
        existing_nullable=True,
    )
