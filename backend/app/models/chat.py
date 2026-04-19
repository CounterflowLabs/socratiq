"""Pydantic schemas for chat API endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request body for sending a chat message."""
    message: str
    conversation_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None


class ConversationResponse(BaseModel):
    """Response model for a conversation."""
    id: uuid.UUID
    course_id: uuid.UUID | None = None
    mode: str
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Response model for a message."""
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""
    items: list[ConversationResponse]
    total: int
