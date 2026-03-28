"""SQLAlchemy ORM model for episodic memories."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.models.base import Base, BaseMixin


class EpisodicMemory(BaseMixin, Base):
    __tablename__ = "episodic_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    importance: Mapped[float] = mapped_column(Numeric(3, 2), default=0.5)
    embedding = mapped_column(Vector(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_episodic_user_importance", "user_id", "importance"),
        Index(
            "ix_episodic_expires",
            "expires_at",
            postgresql_where="expires_at IS NOT NULL",
        ),
    )
