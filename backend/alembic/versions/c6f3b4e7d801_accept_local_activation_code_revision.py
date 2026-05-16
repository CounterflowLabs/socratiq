"""accept local activation-code revision

Revision ID: c6f3b4e7d801
Revises: b5e2a3f9c8d4
Create Date: 2026-05-16 14:40:00.000000

This revision exists to let local databases that were stamped by an
activation-code branch boot with the current mainline migration graph.
The current application code does not depend on those tables/columns, and
the affected local database already has them, so this migration is
intentionally a no-op.
"""

from typing import Sequence, Union


revision: str = "c6f3b4e7d801"
down_revision: Union[str, Sequence[str], None] = "b5e2a3f9c8d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
