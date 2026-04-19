"""SQLAlchemy ORM model for source processing tasks."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, text
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
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source: Mapped["Source"] = relationship(  # noqa: F821
        "Source", back_populates="tasks"
    )
