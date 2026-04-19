"""add lifecycle fields to source_tasks

Revision ID: c1d2e3f4a5b6
Revises: 4b7c2f1a9d11
Create Date: 2026-04-19 10:45:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "4b7c2f1a9d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("source_tasks", sa.Column("stage", sa.String(length=50), nullable=True))
    op.add_column("source_tasks", sa.Column("error_summary", sa.Text(), nullable=True))
    _backfill_source_tasks(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_tasks", "error_summary")
    op.drop_column("source_tasks", "stage")


def _backfill_source_tasks(bind) -> None:
    """Populate lifecycle fields and repair missing source-processing tasks."""
    sources = sa.table(
        "sources",
        sa.column("id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("metadata_", JSONB()),
        sa.column("celery_task_id", sa.String()),
    )
    source_tasks = sa.table(
        "source_tasks",
        sa.column("id", sa.Uuid()),
        sa.column("source_id", sa.Uuid()),
        sa.column("task_type", sa.String()),
        sa.column("status", sa.String()),
        sa.column("stage", sa.String()),
        sa.column("error_summary", sa.Text()),
        sa.column("celery_task_id", sa.String()),
    )

    existing_rows = bind.execute(
        sa.select(
            source_tasks.c.id.label("task_id"),
            sources.c.status.label("source_status"),
            sources.c.metadata_.label("source_metadata"),
        )
        .select_from(
            source_tasks.join(sources, source_tasks.c.source_id == sources.c.id)
        )
        .where(source_tasks.c.task_type == "source_processing")
    ).mappings().all()

    for row in existing_rows:
        task_status, stage, error_summary = _lifecycle_from_source(
            row["source_status"],
            row["source_metadata"],
        )
        bind.execute(
            sa.update(source_tasks)
            .where(source_tasks.c.id == row["task_id"])
            .values(
                status=task_status,
                stage=stage,
                error_summary=error_summary,
            )
        )

    missing_rows = bind.execute(
        sa.select(
            sources.c.id.label("source_id"),
            sources.c.status.label("source_status"),
            sources.c.metadata_.label("source_metadata"),
            sources.c.celery_task_id.label("celery_task_id"),
        )
        .select_from(
            sources.outerjoin(
                source_tasks,
                sa.and_(
                    source_tasks.c.source_id == sources.c.id,
                    source_tasks.c.task_type == "source_processing",
                ),
            )
        )
        .where(
            sources.c.celery_task_id.isnot(None),
            source_tasks.c.id.is_(None),
        )
    ).mappings().all()

    for row in missing_rows:
        task_status, stage, error_summary = _lifecycle_from_source(
            row["source_status"],
            row["source_metadata"],
        )
        bind.execute(
            sa.insert(source_tasks).values(
                id=uuid.uuid4(),
                source_id=row["source_id"],
                task_type="source_processing",
                status=task_status,
                stage=stage,
                error_summary=error_summary,
                celery_task_id=row["celery_task_id"],
            )
        )


def _lifecycle_from_source(
    source_status: str | None,
    source_metadata: dict | None,
) -> tuple[str, str, str | None]:
    """Map a source row to the persisted task lifecycle fields."""
    metadata = source_metadata or {}
    error_summary = metadata.get("error") if isinstance(metadata, dict) else None

    if source_status == "pending":
        return "pending", "pending", None
    if source_status == "ready":
        return "success", "ready", None
    if source_status == "error":
        return "failure", "error", error_summary
    return "running", source_status or "pending", None
