"""Agent tools for exercise generation and evaluation."""

import json
import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool, tool_error
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
            "Generate 1-5 fresh practice exercises for a specific course section. "
            "Reads the section's content, asks the LLM to write `mcq`, `code`, or "
            "`open` questions, and persists them to the exercise bank.\n\n"
            "## Use when\n"
            "- The student finished a section and wants practice — generate then offer them\n"
            "- You diagnosed a weak spot tied to a specific section and want a targeted drill\n"
            "- The section's existing exercise bank doesn't cover the angle you want to test\n\n"
            "## Don't use when\n"
            "- You just want to ASK the student a Socratic question inline — don't generate, just ask\n"
            "- The section already has plenty of unattempted exercises — query first, generate only if needed\n"
            "- The student is mid-flow on a concept — don't interrupt with exercise generation\n\n"
            "## Example of misuse\n"
            "Student: \"Can you give me a quick check on this?\"\n"
            "Mentor: [calls generate_exercises count=5]\n"
            "→ wrong; \"quick check\" wants one inline question, not 5 persisted exercises. Just ask the question."
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
            return tool_error(
                message=f"Invalid section_id (not a UUID): {section_id_str!r}",
                reason="invalid_uuid",
                suggestion="section_id must be a UUID string returned by an earlier tool call — don't synthesize one.",
            )

        # Fetch the section
        result = await self._db.execute(select(Section).where(Section.id == section_uuid))
        section = result.scalar_one_or_none()
        if not section:
            return tool_error(
                message=f"Section {section_id_str} not found",
                reason="section_not_found",
                suggestion="The section_id may belong to a different course or have been deleted. Verify against the course outline before retrying.",
            )

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
            return tool_error(
                message="LLM failed to generate any exercises for this section",
                reason="generation_empty",
                suggestion="The section content may be too thin to generate exercises from. Tell the student the section needs more material before drilling on it.",
            )

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
            "Grade a student's answer to a specific exercise from the bank. "
            "Persists the submission, runs LLM-based grading, returns "
            "score+feedback, and updates spaced-repetition schedules for the "
            "exercise's concepts.\n\n"
            "## Use when\n"
            "- The student typed an answer to an exercise you (or a previous tool call) showed them\n"
            "- The student wants their answer reviewed for correctness/feedback\n\n"
            "## Don't use when\n"
            "- The student answered an inline Socratic question (not from the exercise bank) — those don't have an exercise_id and shouldn't go through grading\n"
            "- You only need to give feedback verbally without persisting — just answer in chat\n"
            "- You don't have a real exercise_id from a prior `generate_exercises` call or section query\n\n"
            "## Example of misuse\n"
            "Mentor: \"What's the time complexity of binary search?\" (inline Socratic)\n"
            "Student: \"O(log n)\"\n"
            "Mentor: [calls evaluate_exercise with a made-up exercise_id]\n"
            "→ wrong; this was an inline question, not a bank exercise. Just acknowledge in chat."
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
            return tool_error(
                message=f"Invalid exercise_id (not a UUID): {exercise_id_str!r}",
                reason="invalid_uuid",
                suggestion="exercise_id must be a UUID string returned by an earlier tool call (e.g. generate_exercises) — don't synthesize one.",
            )

        # Fetch exercise
        exercise = await self._db.get(Exercise, exercise_uuid)
        if not exercise:
            return tool_error(
                message=f"Exercise {exercise_id_str} not found",
                reason="exercise_not_found",
                suggestion="The exercise_id may belong to a different student/course or have been deleted. Verify the id was returned from a recent tool call before retrying.",
            )

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
