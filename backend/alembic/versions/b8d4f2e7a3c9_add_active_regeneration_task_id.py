"""add active regeneration task id to courses

Revision ID: b8d4f2e7a3c9
Revises: a7c3b9e21f01
Create Date: 2026-04-26 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d4f2e7a3c9"
down_revision: Union[str, Sequence[str], None] = "a7c3b9e21f01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("active_regeneration_task_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "active_regeneration_task_id")
