"""merge section progress and bilibili credential heads

Revision ID: f0e1d2c3b4a5
Revises: 8650c9317bb1, c46e39d7e515
Create Date: 2026-04-18 10:35:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, Sequence[str], None] = (
    "8650c9317bb1",
    "c46e39d7e515",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration branches."""


def downgrade() -> None:
    """Unmerge migration branches."""
