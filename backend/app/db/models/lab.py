"""SQLAlchemy ORM model for code labs."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Lab(BaseMixin, Base):
    __tablename__ = "labs"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    starter_code: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    test_code: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    solution_code: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    run_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=0.5)
