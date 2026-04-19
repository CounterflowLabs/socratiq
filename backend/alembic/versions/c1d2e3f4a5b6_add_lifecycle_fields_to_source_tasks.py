"""add lifecycle fields to source_tasks

Revision ID: c1d2e3f4a5b6
Revises: 4b7c2f1a9d11
Create Date: 2026-04-19 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "4b7c2f1a9d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("source_tasks", sa.Column("stage", sa.String(length=50), nullable=True))
    op.add_column("source_tasks", sa.Column("error_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_tasks", "error_summary")
    op.drop_column("source_tasks", "stage")
