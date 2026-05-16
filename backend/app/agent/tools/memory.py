"""Agent tools for episodic memory and metacognitive reflection."""

import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool, tool_error
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
            "Long-term memory of THIS student's learning events. Two actions: "
            "`record` saves a noteworthy moment for future sessions; `recall` "
            "retrieves past events to inform the current explanation.\n\n"
            "## Use when (record)\n"
            "- The student just had a clear breakthrough (\"oh! I get it now\") — record an `aha_moment`\n"
            "- The student got stuck on a concept that prerequisites/profile didn't predict — record a `stuck` event\n"
            "- The student stated a preference that should persist (\"I learn better with diagrams\") — record a `preference`\n"
            "- The student made the same mistake type twice — record a `mistake`\n\n"
            "## Use when (recall)\n"
            "- About to explain a concept and want to check if a prior `aha_moment` analogy worked\n"
            "- The student seems stuck and you want to see if they've been stuck on this exact thing before\n"
            "- Personalizing the opening of a new topic with a callback to past progress\n\n"
            "## Don't use when\n"
            "- Recording trivia (\"student answered correctly\") — that goes through `track_progress`, not here. This is for emotionally-loaded or pedagogically-load-bearing moments only\n"
            "- Recalling at the start of every turn \"just in case\" — only call when you have a specific hypothesis to check\n"
            "- The fact is in the student profile (`learning_style`, `weak_spots`) — read profile instead, it's faster\n\n"
            "## Example of misuse\n"
            "Student: \"I think I understand now.\"\n"
            "Mentor: [calls episodic_memory record event_type=aha_moment]\n"
            "→ premature; \"I think\" isn't a clear breakthrough. Verify with one more question first."
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
        return tool_error(
            message=f"Unknown action: {action!r}",
            reason="invalid_action",
            suggestion="Pass action='record' to save an event, or action='recall' to search past events.",
        )

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
            "Record an observation about whether a specific teaching strategy "
            "(code_first, analogy, visual, step_by_step, socratic, direct) just "
            "worked or fell flat for this student. Used to adapt future pedagogy.\n\n"
            "## Use when\n"
            "- You just used a strategy and have direct evidence of effectiveness (student got it / didn't get it)\n"
            "- You're noting a CONTRAST: \"the analogy worked where the formal definition didn't\" — record both\n"
            "- The strategy result surprises you given the student's profile (worth saving so the next session updates the model)\n\n"
            "## Don't use when\n"
            "- You're guessing at effectiveness without evidence — wait for the student's response first\n"
            "- The signal is ambiguous (\"hmm, ok\") — only record on clear positive/negative\n"
            "- You're tempted to record at the end of every turn — this is a sparse signal, not a heartbeat\n\n"
            "## Example of misuse\n"
            "[no student response yet]\n"
            "Mentor: [calls metacognitive_reflect strategy=analogy effectiveness=0.8]\n"
            "→ wrong; you haven't seen the analogy land yet. Wait for the student's reply, then judge."
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
