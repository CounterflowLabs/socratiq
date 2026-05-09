"""add cancel_requested to source_tasks

Revision ID: c5e7a9b1d3f2
Revises: b8d4f2e7a3c9
Create Date: 2026-05-09 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e7a9b1d3f2"
down_revision: Union[str, Sequence[str], None] = "b8d4f2e7a3c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cancel_requested flag for cooperative task cancellation."""
    op.add_column(
        "source_tasks",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("source_tasks", "cancel_requested")
