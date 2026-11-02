"""add_gin_full_text_indexes_for_retrieval

Revision ID: 07d25c09fdde
Revises: f8d6aac5883a
Create Date: 2026-11-02 19:57:11.682023

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07d25c09fdde'
down_revision: Union[str, Sequence[str], None] = 'f8d6aac5883a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX ix_project_memories_tsv ON project_memories "
        "USING gin (to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(content, '')))"
    )
    op.execute(
        "CREATE INDEX ix_artifacts_tsv ON artifacts "
        "USING gin (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(file_path, '')))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_artifacts_tsv")
    op.execute("DROP INDEX IF EXISTS ix_project_memories_tsv")
