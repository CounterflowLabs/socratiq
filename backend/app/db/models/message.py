"""SQLAlchemy ORM model for the messages table."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Message(BaseMixin, Base):
    """Represents a single message within a conversation.

    Attributes:
        conversation_id: UUID foreign key referencing the parent conversation.
        role: Message role — 'user', 'assistant', or 'tool_result'.
        content: The message text content.
        tool_calls: Optional JSONB array of tool call records.
        metadata_: Optional JSONB metadata (named with trailing underscore
            to avoid collision with SQLAlchemy's internal ``metadata``).
    """

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata_", JSONB, nullable=True
    )
