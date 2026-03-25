"""SQLAlchemy ORM model for subtitle translations."""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Translation(BaseMixin, Base):
    __tablename__ = "translations"

    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_chunks.id"), nullable=False, index=True)
    target_lang: Mapped[str] = mapped_column(String(10), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("chunk_id", "target_lang", name="uq_translation_chunk_lang"),
    )
