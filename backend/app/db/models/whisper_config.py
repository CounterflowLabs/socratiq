"""SQLAlchemy ORM model for Whisper ASR configuration."""

import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class WhisperConfig(BaseMixin, Base):
    """Whisper ASR configuration. One row per user (NULL user_id = system default)."""

    __tablename__ = "whisper_configs"

    mode: Mapped[str] = mapped_column(String(20), server_default=text("'api'"), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    local_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True
    )
