"""SQLAlchemy ORM model for metacognitive learning records."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class MetacognitiveRecord(BaseMixin, Base):
    __tablename__ = "metacognitive_records"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    effectiveness: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_metacog_user_eff", "user_id", "effectiveness"),
    )
