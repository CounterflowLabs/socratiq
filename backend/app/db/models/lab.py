"""SQLAlchemy ORM model for the labs table."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Lab(BaseMixin, Base):
    """Represents a hands-on coding lab tied to a course section.

    Attributes:
        section_id: UUID foreign key referencing the parent section.
        title: Lab title.
        description: Optional description of the lab.
        difficulty: Difficulty level (1-based integer scale).
        estimated_minutes: Optional estimated completion time in minutes.
        starter_code: Optional starter code template.
        solution: Optional reference solution.
        test_cases: JSONB array of test case definitions.
        hints: JSONB array of progressive hints.
    """

    __tablename__ = "labs"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    difficulty: Mapped[int] = mapped_column(default=1)
    estimated_minutes: Mapped[int | None] = mapped_column(nullable=True)
    starter_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_cases: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'"), nullable=False
    )
    hints: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'"), nullable=False
    )
