"""add active_exercise_task_id + exercise_generation_error to sections

Revision ID: d6f4a8b2e7c1
Revises: c5e7a9b1d3f2
Create Date: 2026-05-10 02:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f4a8b2e7c1"
down_revision: Union[str, Sequence[str], None] = "c5e7a9b1d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-section lock + last-error slot for async exercise generation."""
    op.add_column(
        "sections",
        sa.Column("active_exercise_task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sections",
        sa.Column("exercise_generation_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sections", "exercise_generation_error")
    op.drop_column("sections", "active_exercise_task_id")
