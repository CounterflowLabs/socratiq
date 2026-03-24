"""SQLAlchemy ORM model for the conversations table."""

import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Conversation(BaseMixin, Base):
    """Represents a chat conversation between a user and the mentor agent.

    Attributes:
        user_id: UUID foreign key referencing the user.
        course_id: Optional UUID foreign key referencing a course context.
        mode: Conversation mode — e.g. 'qa', 'socratic', 'review'.
    """

    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id"), nullable=True
    )
    mode: Mapped[str] = mapped_column(
        String, server_default=text("'qa'"), nullable=False
    )
