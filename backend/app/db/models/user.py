"""SQLAlchemy ORM model for the users table."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, text
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

    # Auth fields (Phase 2)
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)

    # Subscription / activation (W4)
    activation_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activation_codes.id"), nullable=True
    )
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    monthly_usd_cap: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Relationships
    sources: Mapped[list["Source"]] = relationship(  # noqa: F821
        "Source", back_populates="creator", lazy="selectin"
    )
