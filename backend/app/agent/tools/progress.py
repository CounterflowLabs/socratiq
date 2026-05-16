"""Learning progress tracking tool for the MentorAgent."""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool, tool_error
from app.db.models.learning_record import LearningRecord


class ProgressTrackTool(AgentTool):
    """Track and query learning progress.

    The MentorAgent uses this to:
    - Record that a student has completed a section or exercise
    - Query what the student has already covered
    - Check recent learning activity
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "track_progress"

    @property
    def description(self) -> str:
        return (
            "Read or write the student's per-course learning event log. Two "
            "actions: `record` appends an event (section_complete, "
            "exercise_attempt, video_watch, chat); `query` returns the most "
            "recent ~50 events for a course.\n\n"
            "## Use when (record)\n"
            "- The student just finished a section — record `section_complete`\n"
            "- The student just attempted an exercise (independent of grading) — record `exercise_attempt`\n"
            "- The student watched a video segment to completion — record `video_watch`\n\n"
            "## Use when (query)\n"
            "- Deciding what to teach next and need to know what's already covered\n"
            "- The student asks \"where was I?\" or \"what have I done so far?\"\n"
            "- About to recommend a section and want to check it isn't already complete\n\n"
            "## Don't use when\n"
            "- Recording a chat exchange — every turn already triggers profile updates; this would be noise\n"
            "- Recording a `breakthrough` or `aha_moment` — that goes through `episodic_memory`, not here\n"
            "- Querying without a `course_id` when you do know the course — narrows the result and is much more useful\n\n"
            "## Example of misuse\n"
            "Student: \"Got it.\"\n"
            "Mentor: [calls track_progress action=record record_type=chat]\n"
            "→ wrong; \"Got it\" is a one-line acknowledgment, not a learning event worth logging."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["record", "query"],
                    "description": "'record' to log a learning event, 'query' to check progress.",
                },
                "course_id": {
                    "type": "string",
                    "description": "UUID of the course.",
                },
                "section_id": {
                    "type": "string",
                    "description": "UUID of the section (optional for query, required for record).",
                },
                "record_type": {
                    "type": "string",
                    "description": "Type of learning event: 'section_complete', 'exercise_attempt', 'video_watch', 'chat'.",
                },
                "data": {
                    "type": "object",
                    "description": "Additional data for the learning event (e.g. score, time_spent).",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        course_id: str | None = None,
        section_id: str | None = None,
        record_type: str | None = None,
        data: dict | None = None,
    ) -> str:
        if action == "record":
            return await self._record(course_id, section_id, record_type, data)
        elif action == "query":
            return await self._query(course_id)
        return tool_error(
            message=f"Unknown action: {action!r}",
            reason="invalid_action",
            suggestion="Pass action='record' to log an event, or action='query' to read the event log.",
        )

    async def _record(
        self,
        course_id: str | None,
        section_id: str | None,
        record_type: str | None,
        data: dict | None,
    ) -> str:
        if not record_type:
            return tool_error(
                message="record_type is required for action='record'",
                reason="missing_record_type",
                suggestion=(
                    "Pass record_type as one of: section_complete, exercise_attempt, "
                    "video_watch, chat — pick the one that best describes the event."
                ),
            )

        try:
            record = LearningRecord(
                user_id=self._user_id,
                course_id=uuid.UUID(course_id) if course_id else None,
                section_id=uuid.UUID(section_id) if section_id else None,
                type=record_type,
                data=data or {},
            )
        except ValueError as exc:
            return tool_error(
                message=f"Invalid UUID in course_id or section_id: {exc}",
                reason="invalid_uuid",
                suggestion="course_id and section_id must be valid UUID strings — read them from a tool result, not synthesized.",
            )
        self._db.add(record)
        await self._db.flush()
        return f"Recorded learning event: {record_type}"

    async def _query(self, course_id: str | None) -> str:
        stmt = (
            select(LearningRecord)
            .where(LearningRecord.user_id == self._user_id)
            .order_by(LearningRecord.created_at.desc())
            .limit(50)
        )
        if course_id:
            stmt = stmt.where(LearningRecord.course_id == uuid.UUID(course_id))

        result = await self._db.execute(stmt)
        records = result.scalars().all()

        if not records:
            return "No learning records found."

        summary = []
        for r in records:
            summary.append({
                "type": r.type,
                "section_id": str(r.section_id) if r.section_id else None,
                "data": r.data,
                "created_at": r.created_at.isoformat(),
            })
        return json.dumps(summary, indent=2, ensure_ascii=False)
