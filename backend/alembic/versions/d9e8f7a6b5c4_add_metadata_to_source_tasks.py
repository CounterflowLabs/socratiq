"""add metadata to source_tasks

Revision ID: d9e8f7a6b5c4
Revises: c1d2e3f4a5b6
Create Date: 2026-04-19 16:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d9e8f7a6b5c4"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "source_tasks",
        sa.Column(
            "metadata_",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE source_tasks
            SET metadata_ = '{}'::jsonb
            WHERE metadata_ IS NULL
            """
        )
    )
    op.alter_column("source_tasks", "metadata_", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_tasks", "metadata_")
