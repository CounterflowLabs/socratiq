"""SQLAlchemy ORM model for the content_chunks table."""

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class ContentChunk(BaseMixin, Base):
    """Represents a chunk of content extracted from a source.

    Attributes:
        source_id: UUID foreign key referencing the parent source.
        section_id: Optional UUID foreign key referencing a course section.
        text: The textual content of this chunk.
        embedding: Optional vector embedding for RAG retrieval.
        metadata_: Arbitrary JSONB metadata (named with trailing underscore
            to avoid collision with SQLAlchemy's internal ``metadata``).
    """

    __tablename__ = "content_chunks"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata_", JSONB, server_default=sa_text("'{}'"), nullable=False
    )
