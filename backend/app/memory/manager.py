"""5-layer memory manager for the MentorAgent."""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.episodic_memory import EpisodicMemory
from app.db.models.message import Message
from app.db.models.metacognitive_record import MetacognitiveRecord
from app.db.models.learning_record import LearningRecord
from app.services.profile import StudentProfile, load_profile

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """Aggregated memory from all 5 layers.

    Layers:
        working:        Recent conversation messages (short-term context).
        profile:        Student profile (competency, style, goals).
        episodic:       Noteworthy learning events (stuck, breakthrough, etc.).
        content:        RAG search results (populated externally by KnowledgeSearchTool).
        progress:       Learning records (section completions, exercise attempts).
        metacognitive:  Effective teaching strategies for this student.
    """

    working: list[dict] = field(default_factory=list)
    profile: StudentProfile = field(default_factory=StudentProfile)
    episodic: list[dict] = field(default_factory=list)
    content: list[dict] = field(default_factory=list)
    progress: list[dict] = field(default_factory=list)
    metacognitive: list[dict] = field(default_factory=list)


class MemoryManager:
    """Retrieves and assembles the 5-layer memory context for a user.

    The content layer is intentionally left empty here because RAG search
    is handled separately by KnowledgeSearchTool during the agent loop.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def retrieve(
        self,
        user_id: UUID,
        query: str,
        conversation_id: UUID | None = None,
        course_id: UUID | None = None,
    ) -> MemoryContext:
        """Retrieve all memory layers for the given user and context.

        Args:
            user_id: The student's UUID.
            query: Current user message (unused for now; reserved for
                   future vector-based episodic recall).
            conversation_id: If set, loads recent messages as working memory.
            course_id: If set, scopes progress records to this course.

        Returns:
            A MemoryContext with all layers populated.
        """
        working = (
            await self._get_recent_messages(conversation_id)
            if conversation_id
            else []
        )
        profile = await load_profile(self._db, user_id)
        episodic = await self._search_episodic(user_id, limit=5)
        progress = await self._get_progress(user_id, course_id)
        metacognitive = await self._get_effective_strategies(user_id)

        return MemoryContext(
            working=working,
            profile=profile,
            episodic=episodic,
            content=[],  # RAG search done separately by KnowledgeSearchTool
            progress=progress,
            metacognitive=metacognitive,
        )

    async def _get_recent_messages(
        self, conversation_id: UUID, limit: int = 20
    ) -> list[dict]:
        """Layer 1 - Working memory: recent conversation messages."""
        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    async def _search_episodic(
        self, user_id: UUID, limit: int = 5
    ) -> list[dict]:
        """Layer 3 - Episodic memory: important learning events."""
        result = await self._db.execute(
            select(EpisodicMemory)
            .where(EpisodicMemory.user_id == user_id)
            .order_by(
                EpisodicMemory.importance.desc(),
                EpisodicMemory.created_at.desc(),
            )
            .limit(limit)
        )
        return [
            {
                "event_type": m.event_type,
                "content": m.content,
                "importance": float(m.importance),
            }
            for m in result.scalars().all()
        ]

    async def _get_progress(
        self, user_id: UUID, course_id: UUID | None
    ) -> list[dict]:
        """Layer 5 - Progress memory: learning records."""
        q = select(LearningRecord).where(LearningRecord.user_id == user_id)
        if course_id:
            q = q.where(LearningRecord.course_id == course_id)
        q = q.order_by(LearningRecord.created_at.desc()).limit(10)
        result = await self._db.execute(q)
        return [
            {"type": r.type, "data": r.data}
            for r in result.scalars().all()
        ]

    async def _get_effective_strategies(
        self, user_id: UUID, limit: int = 5
    ) -> list[dict]:
        """Layer 5+ - Metacognitive memory: what teaching strategies work."""
        result = await self._db.execute(
            select(MetacognitiveRecord)
            .where(
                MetacognitiveRecord.user_id == user_id,
                MetacognitiveRecord.effectiveness >= 0.6,
            )
            .order_by(MetacognitiveRecord.effectiveness.desc())
            .limit(limit)
        )
        return [
            {
                "strategy": r.strategy,
                "effectiveness": float(r.effectiveness),
                "evidence": r.evidence,
            }
            for r in result.scalars().all()
        ]
