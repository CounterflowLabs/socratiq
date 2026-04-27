"""API routes for exercises and submissions."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.course import Section
from app.db.models.exercise import Exercise
from app.db.models.exercise_submission import ExerciseSubmission
from app.db.models.user import User
from app.services.exercise import ExerciseService
from app.services.llm.router import ModelRouter, TaskType
from app.services.profile import load_profile

router = APIRouter(prefix="/api/v1/exercises", tags=["exercises"])


class ExerciseResponse(BaseModel):
    id: uuid.UUID
    section_id: uuid.UUID
    type: str
    question: str
    options: Any | None
    explanation: str | None
    difficulty: int
    concepts: list[uuid.UUID]

    model_config = {"from_attributes": True}


class SubmitAnswerRequest(BaseModel):
    answer: str


class SubmitAnswerResponse(BaseModel):
    submission_id: uuid.UUID
    exercise_id: uuid.UUID
    attempt_number: int
    score: float | None
    feedback: str | None
    correct: bool | None
    explanation: str | None = None


class ExerciseListResponse(BaseModel):
    items: list[ExerciseResponse]
    total: int


class GenerateExercisesRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=10)
    types: list[str] | None = None


@router.get("/{exercise_id}", response_model=ExerciseResponse)
async def get_exercise(
    exercise_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> ExerciseResponse:
    """Get a single exercise by ID. Answer and correct_index are excluded."""
    exercise = await db.get(Exercise, exercise_id)
    if not exercise:
        raise HTTPException(404, f"Exercise {exercise_id} not found")

    return ExerciseResponse(
        id=exercise.id,
        section_id=exercise.section_id,
        type=exercise.type,
        question=exercise.question,
        options=exercise.options,
        explanation=None,  # withheld until submission
        difficulty=exercise.difficulty,
        concepts=exercise.concepts,
    )


@router.post("/{exercise_id}/submit", response_model=SubmitAnswerResponse)
async def submit_answer(
    exercise_id: uuid.UUID,
    request: SubmitAnswerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> SubmitAnswerResponse:
    """Submit an answer to an exercise. Grades it and returns the result."""
    exercise = await db.get(Exercise, exercise_id)
    if not exercise:
        raise HTTPException(404, f"Exercise {exercise_id} not found")

    # Determine attempt number
    count_result = await db.execute(
        select(func.count(ExerciseSubmission.id)).where(
            ExerciseSubmission.exercise_id == exercise_id,
            ExerciseSubmission.user_id == user.id,
        )
    )
    attempt_number = (count_result.scalar() or 0) + 1

    # Save submission first
    submission = ExerciseSubmission(
        user_id=user.id,
        exercise_id=exercise_id,
        answer=request.answer,
        attempt_number=attempt_number,
    )
    db.add(submission)
    await db.flush()

    # Grade via ExerciseService
    provider = await model_router.get_provider(TaskType.EVALUATION)
    service = ExerciseService(provider)
    result = await service.evaluate_submission(
        question=exercise.question,
        answer=request.answer,
        correct_answer=exercise.answer or "",
        exercise_type=exercise.type,
    )

    score = result.get("score")
    feedback = result.get("feedback")

    # Update submission with grading results
    submission.score = score
    submission.feedback = feedback

    correct: bool | None = None
    if score is not None:
        correct = float(score) >= 80.0

    await db.commit()

    # Auto-update section progress with best exercise score
    if submission.score is not None:
        from app.db.models import SectionProgress
        progress = (await db.execute(
            select(SectionProgress).where(
                SectionProgress.user_id == user.id,
                SectionProgress.section_id == exercise.section_id,
            )
        )).scalar_one_or_none()
        if not progress:
            progress = SectionProgress(user_id=user.id, section_id=exercise.section_id)
            db.add(progress)
        if progress.exercise_best_score is None or submission.score > progress.exercise_best_score:
            progress.exercise_best_score = submission.score
        await db.commit()

    return SubmitAnswerResponse(
        submission_id=submission.id,
        exercise_id=exercise_id,
        attempt_number=attempt_number,
        score=score,
        feedback=feedback,
        correct=correct,
        explanation=exercise.explanation,
    )


@router.get("/section/{section_id}", response_model=ExerciseListResponse)
async def list_exercises_for_section(
    section_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> ExerciseListResponse:
    """List all exercises for a given section."""
    result = await db.execute(
        select(Exercise)
        .where(Exercise.section_id == section_id)
        .order_by(Exercise.difficulty)
    )
    exercises = result.scalars().all()

    items = [
        ExerciseResponse(
            id=ex.id,
            section_id=ex.section_id,
            type=ex.type,
            question=ex.question,
            options=ex.options,
            explanation=None,
            difficulty=ex.difficulty,
            concepts=ex.concepts,
        )
        for ex in exercises
    ]
    return ExerciseListResponse(items=items, total=len(items))


def _extract_lesson_content(section_content: dict | None) -> str:
    """Pull readable lesson text from a Section.content blob for exercise generation."""
    if not section_content:
        return ""
    lesson = section_content.get("lesson") or {}
    parts: list[str] = []
    if lesson.get("summary"):
        parts.append(str(lesson["summary"]))
    for block in lesson.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"intro_card", "prose", "recap", "next_step"}:
            body = block.get("body")
            if body:
                parts.append(str(body))
    if not parts and section_content.get("summary"):
        parts.append(str(section_content["summary"]))
    return "\n\n".join(parts)


@router.post(
    "/section/{section_id}/generate",
    response_model=ExerciseListResponse,
    status_code=201,
)
async def generate_exercises_for_section(
    section_id: uuid.UUID,
    request: GenerateExercisesRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> ExerciseListResponse:
    """Generate (and persist) practice exercises for a section.

    Idempotency note: this always creates new rows; callers that want to
    avoid duplicates should check ``GET /section/{section_id}`` first.
    """
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(404, f"Section {section_id} not found")

    content = _extract_lesson_content(section.content)
    if not content.strip():
        raise HTTPException(
            400, "Section has no lesson content to generate exercises from."
        )

    profile = await load_profile(db, user.id)

    provider = await model_router.get_provider(TaskType.EVALUATION)
    service = ExerciseService(provider)
    raw_items = await service.generate_from_content(
        content=content,
        count=request.count,
        types=request.types,
        target_language=profile.preferred_language,
    )

    created: list[Exercise] = []
    for item in raw_items:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        exercise = Exercise(
            section_id=section_id,
            type=str(item.get("type") or "open"),
            question=str(item["question"]),
            options=item.get("options"),
            answer=item.get("answer"),
            explanation=item.get("explanation"),
            difficulty=int(item.get("difficulty") or 3),
            concepts=[],
        )
        db.add(exercise)
        created.append(exercise)
    await db.commit()
    for ex in created:
        await db.refresh(ex)

    items = [
        ExerciseResponse(
            id=ex.id,
            section_id=ex.section_id,
            type=ex.type,
            question=ex.question,
            options=ex.options,
            explanation=None,
            difficulty=ex.difficulty,
            concepts=ex.concepts,
        )
        for ex in created
    ]
    return ExerciseListResponse(items=items, total=len(items))
