"""Agent tools for episodic memory and metacognitive reflection."""

import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.db.models.episodic_memory import EpisodicMemory
from app.db.models.metacognitive_record import MetacognitiveRecord
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class EpisodicMemoryTool(AgentTool):
    """Record and recall episodic learning memories.

    The MentorAgent uses this to:
    - Record key learning events (breakthroughs, stuck points, preferences)
    - Recall relevant past experiences to inform current teaching
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "episodic_memory"

    @property
    def description(self) -> str:
        return (
            "Record key learning events or recall past learning experiences. "
            "Use 'record' to save noteworthy moments (stuck, breakthrough, preference) "
            "and 'recall' to find relevant past experiences."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["record", "recall"],
                    "description": "'record' to save an event, 'recall' to search past events.",
                },
                "event_type": {
                    "type": "string",
                    "description": (
                        "For record: stuck, breakthrough, preference, mistake, aha_moment"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "For record: description of the event. "
                        "For recall: search query."
                    ),
                },
                "importance": {
                    "type": "number",
                    "description": "For record: 0.0-1.0 importance score",
                    "default": 0.5,
                },
                "context": {
                    "type": "object",
                    "description": "Optional context: course_id, section_id, concept_id",
                },
                "limit": {
                    "type": "integer",
                    "description": "For recall: max results",
                    "default": 5,
                },
            },
            "required": ["action", "content"],
        }

    async def execute(self, **params) -> str:
        action = params["action"]
        content = params["content"]

        if action == "record":
            return await self._record(content, params)
        elif action == "recall":
            return await self._recall(params)
        return json.dumps({"error": f"Unknown action: {action}"})

    async def _record(self, content: str, params: dict) -> str:
        """Record an episodic memory event."""
        importance = params.get("importance", 0.5)

        # Skip low-importance events to avoid noise
        if importance < 0.2:
            return json.dumps({"status": "skipped", "reason": "importance below threshold"})

        event_type = params.get("event_type", "observation")
        context = params.get("context", {})

        # Set TTL for low-importance memories so they auto-expire
        expires_at = None
        if importance < 0.3:
            expires_at = datetime.utcnow() + timedelta(days=90)  # noqa: DTZ003

        memory = EpisodicMemory(
            user_id=self._user_id,
            event_type=event_type,
            content=content,
            context=context,
            importance=importance,
            expires_at=expires_at,
        )
        self._db.add(memory)
        await self._db.flush()
        return json.dumps({"status": "recorded", "id": str(memory.id)})

    async def _recall(self, params: dict) -> str:
        """Recall episodic memories ordered by importance."""
        limit = params.get("limit", 5)
        # Text-based retrieval; vector search would need embedding computation
        result = await self._db.execute(
            select(EpisodicMemory)
            .where(EpisodicMemory.user_id == self._user_id)
            .order_by(
                EpisodicMemory.importance.desc(),
                EpisodicMemory.created_at.desc(),
            )
            .limit(limit)
        )
        memories = result.scalars().all()
        return json.dumps({
            "memories": [
                {
                    "event_type": m.event_type,
                    "content": m.content,
                    "importance": float(m.importance),
                }
                for m in memories
            ]
        })


class MetacognitiveReflectTool(AgentTool):
    """Reflect on and record teaching strategy effectiveness.

    The MentorAgent uses this to track which teaching approaches
    (code_first, analogy, step_by_step, etc.) work well or poorly
    for a particular student, enabling adaptive pedagogy.
    """

    def __init__(
        self, db: AsyncSession, provider: LLMProvider, user_id: uuid.UUID
    ) -> None:
        self._db = db
        self._provider = provider
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "metacognitive_reflect"

    @property
    def description(self) -> str:
        return (
            "Record observations about which teaching strategies work well "
            "or poorly for this student."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": (
                        "The teaching strategy: code_first, analogy, visual, "
                        "step_by_step, socratic, direct"
                    ),
                },
                "effectiveness": {
                    "type": "number",
                    "description": "0.0 (ineffective) to 1.0 (highly effective)",
                },
                "evidence": {
                    "type": "string",
                    "description": "What happened that suggests this effectiveness level",
                },
                "context": {
                    "type": "object",
                    "description": "Optional context: concept_category, difficulty",
                },
            },
            "required": ["strategy", "effectiveness", "evidence"],
        }

    async def execute(self, **params) -> str:
        record = MetacognitiveRecord(
            user_id=self._user_id,
            strategy=params["strategy"],
            effectiveness=params["effectiveness"],
            context=params.get("context", {}),
            evidence=params["evidence"],
        )
        self._db.add(record)
        await self._db.flush()
        return json.dumps({
            "status": "recorded",
            "strategy": params["strategy"],
            "effectiveness": params["effectiveness"],
        })
