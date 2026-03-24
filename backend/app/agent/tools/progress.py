"""Learning progress tracking tool for the MentorAgent."""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
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
            "Track or query student learning progress. "
            "Use action='record' to log a learning event (e.g. section completed, exercise attempted). "
            "Use action='query' to check what the student has covered in a course."
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
        else:
            return f"Unknown action: {action}"

    async def _record(
        self,
        course_id: str | None,
        section_id: str | None,
        record_type: str | None,
        data: dict | None,
    ) -> str:
        if not record_type:
            return "Error: record_type is required for action='record'"

        record = LearningRecord(
            user_id=self._user_id,
            course_id=uuid.UUID(course_id) if course_id else None,
            section_id=uuid.UUID(section_id) if section_id else None,
            type=record_type,
            data=data or {},
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
