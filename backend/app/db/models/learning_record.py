"""SQLAlchemy ORM model for the learning_records table."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class LearningRecord(BaseMixin, Base):
    """Represents a learning event or activity record for a user.

    Attributes:
        user_id: UUID foreign key referencing the user.
        course_id: Optional UUID foreign key referencing a course.
        section_id: Optional UUID foreign key referencing a section.
        type: Record type (e.g. 'video_watch', 'exercise_attempt', 'quiz_score').
        data: Arbitrary JSONB payload for the learning event.
    """

    __tablename__ = "learning_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id"), nullable=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'"), nullable=False
    )
