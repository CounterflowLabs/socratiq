"""SQLAlchemy ORM model for spaced repetition review items."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class ReviewItem(BaseMixin, Base):
    __tablename__ = "review_items"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exercises.id"), nullable=True)
    easiness: Mapped[float] = mapped_column(Numeric(4, 2), default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    review_at: Mapped[datetime] = mapped_column(nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "concept_id", name="uq_review_user_concept"),
        Index("ix_review_user_due", "user_id", "review_at"),
    )
