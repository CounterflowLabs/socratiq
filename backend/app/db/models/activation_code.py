"""SQLAlchemy ORM model for activation codes (closed-beta paywall)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class ActivationCode(BaseMixin, Base):
    """A pre-generated code redeemed by a user to unlock the beta.

    Carries both the entitlement window (`valid_days`) and the monthly
    LLM spend cap. Single-use: once `redeemed_by_user_id` is set, the
    code cannot be redeemed again.
    """

    __tablename__ = "activation_codes"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_days: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_usd_cap: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
