"""add activation_codes table and user subscription fields

Revision ID: c6f3b4e7d801
Revises: b5e2a3f9c8d4
Create Date: 2026-05-16 14:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6f3b4e7d801"
down_revision: Union[str, Sequence[str], None] = "b5e2a3f9c8d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activation_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.String(length=50), nullable=False),
        sa.Column("valid_days", sa.Integer(), nullable=False),
        sa.Column("monthly_usd_cap", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("redeemed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["redeemed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_activation_codes_code", "activation_codes", ["code"], unique=True
    )
    op.create_index(
        "ix_activation_codes_redeemed_by_user_id",
        "activation_codes",
        ["redeemed_by_user_id"],
    )

    op.add_column("users", sa.Column("activation_code_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("subscription_until", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column("monthly_usd_cap", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_activation_code_id",
        "users",
        "activation_codes",
        ["activation_code_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_activation_code_id", "users", type_="foreignkey")
    op.drop_column("users", "monthly_usd_cap")
    op.drop_column("users", "subscription_until")
    op.drop_column("users", "activation_code_id")
    op.drop_index(
        "ix_activation_codes_redeemed_by_user_id", table_name="activation_codes"
    )
    op.drop_index("ix_activation_codes_code", table_name="activation_codes")
    op.drop_table("activation_codes")
