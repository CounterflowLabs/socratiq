"""add context_window_tokens to model_configs

Revision ID: 5e4b2d4358c5
Revises: c6f3b4e7d801
Create Date: 2026-06-06 15:03:08.092606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5e4b2d4358c5'
down_revision: Union[str, Sequence[str], None] = 'c6f3b4e7d801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Admin-declared input context window for a model. Nullable: NULL ⇒ fall
    # back to the hand-maintained lookup table in services/llm/token_budget.py.
    # (Autogenerate also picked up unrelated schema drift from the shared dev
    # DB — stripped here so this migration only adds this one column.)
    op.add_column(
        'model_configs',
        sa.Column('context_window_tokens', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('model_configs', 'context_window_tokens')
