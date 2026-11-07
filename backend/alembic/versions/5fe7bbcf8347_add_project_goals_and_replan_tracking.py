"""add_project_goals_and_replan_tracking

Revision ID: 5fe7bbcf8347
Revises: 4566f72d5e69
Create Date: 2026-11-07 13:26:01.983139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fe7bbcf8347'
down_revision: Union[str, Sequence[str], None] = '4566f72d5e69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'project_goals',
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('ACTIVE', 'ACHIEVED', 'PAUSED', 'CANCELLED', name='goalstatus', native_enum=False), nullable=False),
        sa.Column('target_criteria', sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column('progress_percentage', sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_goals_project_id'), 'project_goals', ['project_id'], unique=False)
    op.create_index('ix_project_goals_project_status', 'project_goals', ['project_id', 'status'], unique=False)
    op.create_index(op.f('ix_project_goals_status'), 'project_goals', ['status'], unique=False)
    op.add_column(
        'workflow_executions',
        sa.Column('replan_count', sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column('workflow_executions', sa.Column('goal_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_workflow_executions_goal_id'), 'workflow_executions', ['goal_id'], unique=False)
    op.create_foreign_key(
        'fk_workflow_executions_goal_id',
        'workflow_executions',
        'project_goals',
        ['goal_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_workflow_executions_goal_id', 'workflow_executions', type_='foreignkey')
    op.drop_index(op.f('ix_workflow_executions_goal_id'), table_name='workflow_executions')
    op.drop_column('workflow_executions', 'goal_id')
    op.drop_column('workflow_executions', 'replan_count')
    op.drop_index(op.f('ix_project_goals_status'), table_name='project_goals')
    op.drop_index('ix_project_goals_project_status', table_name='project_goals')
    op.drop_index(op.f('ix_project_goals_project_id'), table_name='project_goals')
    op.drop_table('project_goals')
