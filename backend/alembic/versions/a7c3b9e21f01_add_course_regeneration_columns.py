"""add course regeneration columns

Revision ID: a7c3b9e21f01
Revises: d9e8f7a6b5c4
Create Date: 2026-04-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7c3b9e21f01"
down_revision: Union[str, Sequence[str], None] = "d9e8f7a6b5c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("courses", sa.Column("regeneration_directive", sa.Text(), nullable=True))
    op.add_column(
        "courses",
        sa.Column("regeneration_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_courses_parent_id_courses",
        "courses",
        "courses",
        ["parent_id"],
        ["id"],
    )
    op.create_index(
        "ix_courses_parent_id",
        "courses",
        ["parent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_courses_parent_id", table_name="courses")
    op.drop_constraint("fk_courses_parent_id_courses", "courses", type_="foreignkey")
    op.drop_column("courses", "regeneration_metadata")
    op.drop_column("courses", "regeneration_directive")
    op.drop_column("courses", "parent_id")
