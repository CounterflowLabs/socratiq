"""change vector columns to dynamic dimension

Revision ID: bb06294270e4
Revises: 7b674642962a
Create Date: 2026-03-28 17:47:11.164012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb06294270e4'
down_revision: Union[str, Sequence[str], None] = '7b674642962a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove fixed dimension from vector columns to accept any embedding model."""
    op.execute("UPDATE content_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE concepts SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE episodic_memories SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector USING embedding::vector")
    op.execute("ALTER TABLE concepts ALTER COLUMN embedding TYPE vector USING embedding::vector")
    op.execute("ALTER TABLE episodic_memories ALTER COLUMN embedding TYPE vector USING embedding::vector")


def downgrade() -> None:
    """Restore fixed 1536 dimension."""
    op.execute("UPDATE content_chunks SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE concepts SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("UPDATE episodic_memories SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("ALTER TABLE concepts ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("ALTER TABLE episodic_memories ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
