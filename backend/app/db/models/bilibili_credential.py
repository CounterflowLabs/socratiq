"""SQLAlchemy ORM model for Bilibili login credentials."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class BilibiliCredential(BaseMixin, Base):
    """Stored Bilibili login credential (from QR code scan)."""

    __tablename__ = "bilibili_credentials"

    sessdata_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bili_jct_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedeuserid: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True
    )
