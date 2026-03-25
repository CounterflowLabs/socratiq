"""API routes for exercises and submissions."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.exercise import Exercise
from app.db.models.exercise_submission import ExerciseSubmission
from app.db.models.user import User
from app.services.exercise import ExerciseService
from app.services.llm.router import ModelRouter, TaskType

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


class ExerciseListResponse(BaseModel):
    items: list[ExerciseResponse]
    total: int


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

    return SubmitAnswerResponse(
        submission_id=submission.id,
        exercise_id=exercise_id,
        attempt_number=attempt_number,
        score=score,
        feedback=feedback,
        correct=correct,
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
