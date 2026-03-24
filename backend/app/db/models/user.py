"""SQLAlchemy ORM model for the users table."""

import uuid
from typing import Any

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, BaseMixin


class User(BaseMixin, Base):
    """Represents a platform user with an optional student profile.

    Attributes:
        email: Unique email address for the user.
        name: Optional display name.
        student_profile: JSONB field storing adaptive learning profile data.
        sources: Collection of sources created by this user.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    student_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False
    )

    # Relationships
    sources: Mapped[list["Source"]] = relationship(  # noqa: F821
        "Source", back_populates="creator", lazy="selectin"
    )
