"""migrate task_type to tier routing

Revision ID: 942f0ec50aae
Revises: 6d8cec3bdd57
Create Date: 2026-03-28 13:13:02.879912

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '942f0ec50aae'
down_revision: Union[str, Sequence[str], None] = '6d8cec3bdd57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename column task_type -> tier
    op.alter_column('model_route_configs', 'task_type', new_column_name='tier')

    # Migrate data: task_type values -> tier values
    op.execute("UPDATE model_route_configs SET tier = 'primary' WHERE tier = 'mentor_chat'")
    op.execute("UPDATE model_route_configs SET tier = 'light' WHERE tier = 'content_analysis'")
    op.execute("UPDATE model_route_configs SET tier = 'strong' WHERE tier = 'evaluation'")
    # 'embedding' stays 'embedding'

    # Replace unique constraint
    op.drop_constraint('model_route_configs_task_type_key', 'model_route_configs', type_='unique')
    op.create_unique_constraint('uq_model_route_configs_tier', 'model_route_configs', ['tier'])


def downgrade() -> None:
    # Reverse unique constraint
    op.drop_constraint('uq_model_route_configs_tier', 'model_route_configs', type_='unique')
    op.create_unique_constraint('model_route_configs_task_type_key', 'model_route_configs', ['tier'])

    # Reverse data migration
    op.execute("UPDATE model_route_configs SET tier = 'mentor_chat' WHERE tier = 'primary'")
    op.execute("UPDATE model_route_configs SET tier = 'content_analysis' WHERE tier = 'light'")
    op.execute("UPDATE model_route_configs SET tier = 'evaluation' WHERE tier = 'strong'")

    # Rename column back
    op.alter_column('model_route_configs', 'tier', new_column_name='task_type')
