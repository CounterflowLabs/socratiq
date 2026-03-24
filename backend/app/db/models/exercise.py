"""SQLAlchemy ORM model for the exercises table."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Exercise(BaseMixin, Base):
    """Represents a quiz or exercise item tied to a course section.

    Attributes:
        section_id: UUID foreign key referencing the parent section.
        type: Exercise type — one of 'mcq', 'code', 'open'.
        question: The exercise prompt text.
        options: Optional JSONB for multiple-choice options.
        answer: Optional reference answer.
        explanation: Optional answer explanation.
        difficulty: Difficulty level (1-based integer scale).
        concepts: Array of concept UUIDs this exercise covers.
    """

    __tablename__ = "exercises"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(default=1)
    concepts: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
