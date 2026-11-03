"""add_ingestion_operations_and_memory_fingerprint

Revision ID: 7a8e1b2c3d4e
Revises: 07d25c09fdde
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8e1b2c3d4e'
down_revision: Union[str, Sequence[str], None] = '07d25c09fdde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ingestion_operations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('execution_id', sa.UUID(), nullable=True),
        sa.Column('operation_token', sa.String(length=200), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'COMPLETED', 'FAILED', name='ingestionoperationstatus', native_enum=False),
            server_default='PENDING',
            nullable=False,
        ),
        sa.Column('candidate_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('ingested_memory_ids', sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['execution_id'], ['workflow_executions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'operation_token', name='uq_ingestion_operations_project_token'),
    )
    op.create_index(
        'ix_ingestion_operations_project_execution',
        'ingestion_operations',
        ['project_id', 'execution_id'],
        unique=False,
    )

    op.add_column('project_memories', sa.Column('fingerprint', sa.String(length=64), nullable=True))
    op.add_column('project_memories', sa.Column('ingestion_operation_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_project_memories_ingestion_operation_id',
        'project_memories',
        'ingestion_operations',
        ['ingestion_operation_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_project_memories_fingerprint'), 'project_memories', ['fingerprint'], unique=False
    )
    op.create_index(
        op.f('ix_project_memories_ingestion_operation_id'),
        'project_memories',
        ['ingestion_operation_id'],
        unique=False,
    )
    # Enum columns persist member NAMES (ACTIVE/PROPOSED), not lowercase values.
    op.create_index(
        'uq_project_memories_fingerprint',
        'project_memories',
        ['project_id', 'fingerprint'],
        unique=True,
        postgresql_where=sa.text("fingerprint IS NOT NULL AND status IN ('ACTIVE', 'PROPOSED')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_project_memories_fingerprint', table_name='project_memories')
    op.drop_index(op.f('ix_project_memories_ingestion_operation_id'), table_name='project_memories')
    op.drop_index(op.f('ix_project_memories_fingerprint'), table_name='project_memories')
    op.drop_constraint(
        'fk_project_memories_ingestion_operation_id', 'project_memories', type_='foreignkey'
    )
    op.drop_column('project_memories', 'ingestion_operation_id')
    op.drop_column('project_memories', 'fingerprint')
    op.drop_index('ix_ingestion_operations_project_execution', table_name='ingestion_operations')
    op.drop_table('ingestion_operations')
