"""DBMessageStore — MessageStore bound to the existing Conversation/Message tables.

``thread_id`` is the conversation UUID (as a string), matching AG-UI's thread
concept. Loads map ``Message`` rows to ``UnifiedMessage``; appends persist the
text content. Tool-result / structured messages are not replayed into history
(only user/assistant turns), preserving the prior chat behavior.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.message import Message
from app.services.llm.base import ContentBlock, UnifiedMessage

__all__ = ["DBMessageStore"]


def _text_of(message: UnifiedMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(
        b.text or b.tool_result_content or "" for b in message.content
    )


class DBMessageStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load(self, thread_id: str, *, limit: int = 50) -> list[UnifiedMessage]:
        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == uuid.UUID(thread_id))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list(reversed(result.scalars().all()))
        out: list[UnifiedMessage] = []
        for row in rows:
            role = row.role if row.role in ("user", "assistant") else "user"
            out.append(UnifiedMessage(role=role, content=row.content))
        return out

    async def append(self, thread_id: str, message: UnifiedMessage) -> None:
        self._db.add(
            Message(
                conversation_id=uuid.UUID(thread_id),
                role=message.role,
                content=_text_of(message),
            )
        )
        await self._db.flush()
