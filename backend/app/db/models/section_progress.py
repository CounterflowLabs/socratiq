import uuid
from sqlalchemy import Boolean, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models.base import Base, BaseMixin


class SectionProgress(BaseMixin, Base):
    __tablename__ = "section_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "section_id", name="uq_progress_user_section"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    lesson_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    lab_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    exercise_best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
