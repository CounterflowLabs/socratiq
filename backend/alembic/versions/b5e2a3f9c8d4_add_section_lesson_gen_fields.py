"""add active_lesson_task_id + lesson_generation_error to sections

Revision ID: b5e2a3f9c8d4
Revises: d6f4a8b2e7c1
Create Date: 2026-05-14 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5e2a3f9c8d4"
down_revision: Union[str, Sequence[str], None] = "d6f4a8b2e7c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-section lock + last-error slot for async lesson regeneration.

    Mirrors the exercise-generation slots added in d6f4a8b2e7c1. When a
    chunk's lesson LLM call fails, we surface the error on the section
    row instead of fabricating a fake lesson from raw subtitles.
    """
    op.add_column(
        "sections",
        sa.Column("active_lesson_task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sections",
        sa.Column("lesson_generation_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sections", "lesson_generation_error")
    op.drop_column("sections", "active_lesson_task_id")
