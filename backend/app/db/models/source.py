"""SQLAlchemy ORM model for the sources table."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, BaseMixin


class Source(BaseMixin, Base):
    """Represents an ingested content source (video, PDF, markdown, URL).

    Attributes:
        type: Source type — one of 'bilibili', 'pdf', 'markdown', 'url'.
        url: Optional URL for the source content.
        title: Optional human-readable title.
        raw_content: Full extracted text content.
        metadata_: Arbitrary JSONB metadata (named with trailing underscore
            to avoid collision with SQLAlchemy's internal ``metadata``).
        status: Processing pipeline status — 'pending', 'processing', 'ready',
            or 'error'.
        created_by: UUID foreign key referencing the user who created this source.
        creator: Relationship back to the User model.
    """

    __tablename__ = "sources"

    type: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata_", JSONB, server_default=text("'{}'"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, server_default=text("'pending'"), nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    ref_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Relationships
    creator: Mapped["User | None"] = relationship(  # noqa: F821
        "User", back_populates="sources"
    )
