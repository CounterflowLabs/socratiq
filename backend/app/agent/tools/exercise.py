"""Agent tools for exercise generation and evaluation."""

import json
import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.db.models.course import Section
from app.db.models.exercise import Exercise
from app.db.models.exercise_submission import ExerciseSubmission
from app.services.exercise import ExerciseService
from app.services.llm.base import LLMProvider
from app.services.spaced_repetition import SpacedRepetitionService

logger = logging.getLogger(__name__)


class ExerciseGenerateTool(AgentTool):
    """Generate exercises for a course section using LLM."""

    def __init__(self, db: AsyncSession, provider: LLMProvider, user_id: uuid.UUID):
        self._db = db
        self._provider = provider
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "generate_exercises"

    @property
    def description(self) -> str:
        return (
            "Generate practice exercises for a course section. "
            "Analyzes the section content and creates questions of the specified types."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "UUID of the section to generate exercises for.",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of exercises to generate (1-5).",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["mcq", "code", "open"]},
                    "description": "Exercise types to include.",
                },
            },
            "required": ["section_id"],
        }

    async def execute(self, **params) -> str:
        section_id_str = params["section_id"]
        count = int(params.get("count", 3))
        types = params.get("types") or ["mcq", "open"]

        try:
            section_uuid = uuid.UUID(section_id_str)
        except ValueError:
            return json.dumps({"error": f"Invalid section_id: {section_id_str}"})

        # Fetch the section
        result = await self._db.execute(select(Section).where(Section.id == section_uuid))
        section = result.scalar_one_or_none()
        if not section:
            return json.dumps({"error": f"Section {section_id_str} not found"})

        # Build content string from section data
        content_parts = [f"Title: {section.title}"]
        if section.content:
            if isinstance(section.content, dict):
                summary = section.content.get("summary") or section.content.get("text") or ""
                if summary:
                    content_parts.append(summary)
                # Also include any transcript or transcript_summary
                for key in ("transcript_summary", "transcript", "key_points"):
                    val = section.content.get(key)
                    if val:
                        content_parts.append(str(val)[:1000])
            else:
                content_parts.append(str(section.content)[:2000])
        content = "\n\n".join(content_parts)

        service = ExerciseService(self._provider)
        exercises_data = await service.generate_from_content(content, count, types)

        if not exercises_data:
            return json.dumps({"error": "LLM failed to generate exercises", "generated": 0})

        # Persist to DB
        saved = []
        for ex in exercises_data:
            exercise = Exercise(
                section_id=section_uuid,
                type=ex.get("type", "open"),
                question=ex.get("question", ""),
                options=ex.get("options"),
                answer=ex.get("answer"),
                explanation=ex.get("explanation"),
                difficulty=int(ex.get("difficulty", 1)),
                concepts=[],  # concept UUIDs — left empty; agent can resolve later
            )
            self._db.add(exercise)
            saved.append(ex.get("question", ""))

        await self._db.flush()

        return json.dumps({
            "generated": len(saved),
            "section_id": section_id_str,
            "questions": saved,
        })


class ExerciseEvalTool(AgentTool):
    """Evaluate a student's answer to an exercise and update spaced repetition."""

    def __init__(self, db: AsyncSession, provider: LLMProvider, user_id: uuid.UUID):
        self._db = db
        self._provider = provider
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "evaluate_exercise"

    @property
    def description(self) -> str:
        return (
            "Evaluate a student's answer to an exercise. "
            "Saves the submission, grades it, and updates spaced repetition schedules."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "exercise_id": {
                    "type": "string",
                    "description": "UUID of the exercise being answered.",
                },
                "answer": {
                    "type": "string",
                    "description": "The student's answer text.",
                },
            },
            "required": ["exercise_id", "answer"],
        }

    async def execute(self, **params) -> str:
        exercise_id_str = params["exercise_id"]
        answer = params["answer"]

        try:
            exercise_uuid = uuid.UUID(exercise_id_str)
        except ValueError:
            return json.dumps({"error": f"Invalid exercise_id: {exercise_id_str}"})

        # Fetch exercise
        exercise = await self._db.get(Exercise, exercise_uuid)
        if not exercise:
            return json.dumps({"error": f"Exercise {exercise_id_str} not found"})

        # Determine attempt number
        count_result = await self._db.execute(
            select(func.count(ExerciseSubmission.id)).where(
                ExerciseSubmission.exercise_id == exercise_uuid,
                ExerciseSubmission.user_id == self._user_id,
            )
        )
        attempt_number = (count_result.scalar() or 0) + 1

        # Save submission first (before grading)
        submission = ExerciseSubmission(
            user_id=self._user_id,
            exercise_id=exercise_uuid,
            answer=answer,
            attempt_number=attempt_number,
        )
        self._db.add(submission)
        await self._db.flush()

        # Grade
        service = ExerciseService(self._provider)
        result = await service.evaluate_submission(
            question=exercise.question,
            answer=answer,
            correct_answer=exercise.answer or "",
            exercise_type=exercise.type,
        )

        score = result.get("score")
        feedback = result.get("feedback", "")

        # Update submission with score/feedback
        submission.score = score
        submission.feedback = feedback
        await self._db.flush()

        # Trigger spaced repetition for related concepts
        if exercise.concepts and score is not None:
            srs = SpacedRepetitionService(self._db)
            # Map score (0-100) to SM-2 quality (0-5)
            quality = min(5, max(0, round(score / 20)))
            for concept_id in exercise.concepts:
                try:
                    review_item = await srs.get_or_create_review(
                        user_id=self._user_id,
                        concept_id=concept_id,
                        exercise_id=exercise_uuid,
                    )
                    await srs.complete_review(
                        review_id=review_item.id,
                        user_id=self._user_id,
                        quality=quality,
                    )
                except Exception as e:
                    logger.warning(f"SRS update failed for concept {concept_id}: {e}")

        return json.dumps({
            "exercise_id": exercise_id_str,
            "attempt": attempt_number,
            "score": score,
            "feedback": feedback,
            "correct": score == 100.0 if score is not None else None,
        })
