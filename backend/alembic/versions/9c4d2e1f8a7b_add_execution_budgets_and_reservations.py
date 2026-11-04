"""add_execution_budgets_and_reservations

Revision ID: 9c4d2e1f8a7b
Revises: 7a8e1b2c3d4e
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c4d2e1f8a7b'
down_revision: Union[str, Sequence[str], None] = '7a8e1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'execution_budgets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('execution_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        # Limits (NULL = dimension not limited)
        sa.Column('max_cost_usd', sa.Float(), nullable=True),
        sa.Column('max_input_tokens', sa.BigInteger(), nullable=True),
        sa.Column('max_output_tokens', sa.BigInteger(), nullable=True),
        sa.Column('max_total_tokens', sa.BigInteger(), nullable=True),
        sa.Column('max_agent_attempts', sa.Integer(), nullable=True),
        sa.Column('max_task_attempts', sa.Integer(), nullable=True),
        sa.Column('max_remediation_turns', sa.Integer(), nullable=True),
        sa.Column('max_replan_count', sa.Integer(), nullable=True),
        sa.Column('max_runtime_seconds', sa.Integer(), nullable=True),
        # Consumption counters
        sa.Column('consumed_actual_cost_usd', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('consumed_estimated_cost_usd', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_cost_estimated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('consumed_input_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('consumed_output_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('consumed_total_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('consumed_runtime_ms', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_agent_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('remediation_turns_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('replan_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        # Reservations held by in-flight work
        sa.Column('reserved_input_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('reserved_output_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('reserved_cost_usd', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('active_reservations_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'ACTIVE', 'WARNING', 'EXHAUSTED', 'COMPLETED', 'CANCELLED',
                name='budgetstatus', native_enum=False,
            ),
            server_default='ACTIVE',
            nullable=False,
        ),
        sa.Column('exhaustion_reason', sa.String(length=200), nullable=True),
        sa.Column('metadata_json', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.CheckConstraint(
            'max_cost_usd IS NULL OR max_cost_usd >= 0',
            name='ck_execution_budgets_max_cost_nonneg',
        ),
        sa.CheckConstraint(
            'max_input_tokens IS NULL OR max_input_tokens >= 0',
            name='ck_execution_budgets_max_input_tokens_nonneg',
        ),
        sa.CheckConstraint(
            'max_output_tokens IS NULL OR max_output_tokens >= 0',
            name='ck_execution_budgets_max_output_tokens_nonneg',
        ),
        sa.CheckConstraint(
            'max_total_tokens IS NULL OR max_total_tokens >= 0',
            name='ck_execution_budgets_max_total_tokens_nonneg',
        ),
        sa.CheckConstraint(
            'max_agent_attempts IS NULL OR max_agent_attempts >= 0',
            name='ck_execution_budgets_max_agent_attempts_nonneg',
        ),
        sa.CheckConstraint(
            'max_task_attempts IS NULL OR max_task_attempts >= 0',
            name='ck_execution_budgets_max_task_attempts_nonneg',
        ),
        sa.CheckConstraint(
            'max_remediation_turns IS NULL OR max_remediation_turns >= 0',
            name='ck_execution_budgets_max_remediation_turns_nonneg',
        ),
        sa.CheckConstraint(
            'max_replan_count IS NULL OR max_replan_count >= 0',
            name='ck_execution_budgets_max_replan_count_nonneg',
        ),
        sa.CheckConstraint(
            'max_runtime_seconds IS NULL OR max_runtime_seconds >= 0',
            name='ck_execution_budgets_max_runtime_nonneg',
        ),
        sa.CheckConstraint(
            'consumed_actual_cost_usd >= 0 AND consumed_estimated_cost_usd >= 0',
            name='ck_execution_budgets_consumed_cost_nonneg',
        ),
        sa.CheckConstraint(
            'consumed_input_tokens >= 0 AND consumed_output_tokens >= 0 AND consumed_total_tokens >= 0',
            name='ck_execution_budgets_consumed_tokens_nonneg',
        ),
        sa.CheckConstraint(
            'consumed_runtime_ms >= 0 AND total_agent_attempts >= 0 '
            'AND remediation_turns_count >= 0 AND replan_count >= 0',
            name='ck_execution_budgets_consumed_counters_nonneg',
        ),
        sa.CheckConstraint(
            'reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 '
            'AND reserved_cost_usd >= 0 AND active_reservations_count >= 0',
            name='ck_execution_budgets_reserved_nonneg',
        ),
        sa.ForeignKeyConstraint(['execution_id'], ['workflow_executions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_execution_budgets_execution_id', 'execution_budgets', ['execution_id'], unique=True
    )
    op.create_index(
        'ix_execution_budgets_project_id', 'execution_budgets', ['project_id'], unique=False
    )
    op.create_index(
        'ix_execution_budgets_project_status', 'execution_budgets', ['project_id', 'status'], unique=False
    )
    op.create_index('ix_execution_budgets_status', 'execution_budgets', ['status'], unique=False)

    op.create_table(
        'budget_reservations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('budget_id', sa.UUID(), nullable=False),
        # Denormalised from the budget so reservations can be queried per execution without a join.
        sa.Column('execution_id', sa.UUID(), nullable=False),
        sa.Column('reservation_key', sa.String(length=200), nullable=False),
        sa.Column('purpose', sa.String(length=100), nullable=True),
        sa.Column('agent_slug', sa.String(length=100), nullable=True),
        sa.Column('task_id', sa.String(length=100), nullable=True),
        sa.Column('reserved_input_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('reserved_output_tokens', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('reserved_cost_usd', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('reconciled_cost_usd', sa.Float(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'ACTIVE', 'RECONCILED', 'RELEASED', 'EXPIRED',
                name='budgetreservationstatus', native_enum=False,
            ),
            server_default='ACTIVE',
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.CheckConstraint(
            'reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 AND reserved_cost_usd >= 0',
            name='ck_budget_reservations_reserved_nonneg',
        ),
        sa.CheckConstraint(
            'reconciled_cost_usd IS NULL OR reconciled_cost_usd >= 0',
            name='ck_budget_reservations_reconciled_cost_nonneg',
        ),
        sa.ForeignKeyConstraint(['budget_id'], ['execution_budgets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['execution_id'], ['workflow_executions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('budget_id', 'reservation_key', name='uq_budget_reservations_budget_key'),
    )
    op.create_index(
        'ix_budget_reservations_budget_id', 'budget_reservations', ['budget_id'], unique=False
    )
    op.create_index(
        'ix_budget_reservations_execution_id', 'budget_reservations', ['execution_id'], unique=False
    )
    op.create_index(
        'ix_budget_reservations_budget_status', 'budget_reservations', ['budget_id', 'status'], unique=False
    )
    op.create_index('ix_budget_reservations_status', 'budget_reservations', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Child table first: it holds the FK into execution_budgets.
    op.drop_index('ix_budget_reservations_status', table_name='budget_reservations')
    op.drop_index('ix_budget_reservations_budget_status', table_name='budget_reservations')
    op.drop_index('ix_budget_reservations_execution_id', table_name='budget_reservations')
    op.drop_index('ix_budget_reservations_budget_id', table_name='budget_reservations')
    op.drop_table('budget_reservations')

    op.drop_index('ix_execution_budgets_status', table_name='execution_budgets')
    op.drop_index('ix_execution_budgets_project_status', table_name='execution_budgets')
    op.drop_index('ix_execution_budgets_project_id', table_name='execution_budgets')
    op.drop_index('ix_execution_budgets_execution_id', table_name='execution_budgets')
    op.drop_table('execution_budgets')
