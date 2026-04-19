"""SQLAlchemy ORM model for source processing tasks."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, BaseMixin


class SourceTask(BaseMixin, Base):
    """Persisted task record for asynchronous source processing."""

    __tablename__ = "source_tasks"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), server_default=text("'pending'"), nullable=False
    )
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata_", JSONB, server_default=text("'{}'"), nullable=False
    )

    source: Mapped["Source"] = relationship(  # noqa: F821
        "Source", back_populates="tasks"
    )


@event.listens_for(SourceTask, "before_insert")
def _ensure_metadata_column(mapper, connection, target) -> None:
    """Backfill the task metadata column for databases created before this field existed."""
    connection.execute(
        text(
            """
            ALTER TABLE source_tasks
            ADD COLUMN IF NOT EXISTS metadata_ JSONB NOT NULL DEFAULT '{}'::jsonb
            """
        )
    )
