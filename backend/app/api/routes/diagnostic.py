"""API routes for cold-start diagnostic assessment."""

import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, get_model_router
from app.db.models.concept import Concept, ConceptSource
from app.db.models.course import Course, CourseSource
from app.db.models.learning_record import LearningRecord
from app.db.models.user import User
from app.models.diagnostic import DiagnosticAnswer, DiagnosticFullSubmitRequest, DiagnosticResult
from app.services.diagnostic import DiagnosticService
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/courses", tags=["diagnostic"])


class DiagnosticGenerateResponse(BaseModel):
    questions: list[dict]
    concept_map: dict[str, str]  # concept_id (str) -> concept_name


@router.post("/{course_id}/diagnostic/generate", response_model=DiagnosticGenerateResponse)
async def generate_diagnostic(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
    count: int = 5,
) -> DiagnosticGenerateResponse:
    """Generate diagnostic questions for concepts linked to a course.

    Queries concepts via CourseSource -> Source -> ConceptSource -> Concept chain,
    then calls DiagnosticService.generate to produce multiple-choice questions.
    """
    # Verify the course exists and belongs to this user
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.created_by == user.id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    # Get source_ids linked to this course
    cs_result = await db.execute(
        select(CourseSource.source_id).where(CourseSource.course_id == course_id)
    )
    source_ids = [row[0] for row in cs_result.all()]

    if not source_ids:
        raise HTTPException(400, "Course has no linked sources; cannot generate diagnostic")

    # Get concepts linked to those sources
    concepts_result = await db.execute(
        select(Concept)
        .join(ConceptSource, Concept.id == ConceptSource.concept_id)
        .where(ConceptSource.source_id.in_(source_ids))
        .distinct()
    )
    concepts = concepts_result.scalars().all()

    if not concepts:
        raise HTTPException(
            400, "No concepts found for this course; run content analysis first"
        )

    concept_dicts = [
        {"id": str(c.id), "name": c.name, "description": c.description or ""}
        for c in concepts
    ]
    concept_map = {str(c.id): c.name for c in concepts}

    # Get the light model provider for content analysis tasks
    try:
        provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
    except Exception as e:
        logger.warning(f"Could not get content_analysis provider, falling back: {e}")
        try:
            provider = await model_router.get_provider(TaskType.MENTOR_CHAT)
        except Exception as e2:
            raise HTTPException(500, f"No LLM provider available: {e2}") from e2

    service = DiagnosticService(provider)
    try:
        questions = await service.generate(concept_dicts, count=count)
    except Exception as e:
        logger.error(f"DiagnosticService.generate failed: {e}")
        raise HTTPException(500, f"Failed to generate diagnostic questions: {e}") from e

    if not questions:
        raise HTTPException(
            500,
            "LLM failed to produce valid questions; check provider configuration",
        )

    return DiagnosticGenerateResponse(
        questions=[q.model_dump() for q in questions],
        concept_map=concept_map,
    )


@router.post("/{course_id}/diagnostic/submit", response_model=DiagnosticResult)
async def submit_diagnostic(
    course_id: uuid.UUID,
    body: DiagnosticFullSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> DiagnosticResult:
    """Evaluate submitted diagnostic answers and persist a LearningRecord.

    Accepts the original questions (with correct_index and concept_name) plus
    the student's answers, evaluates them, saves a learning record, and returns
    the diagnostic result with level, mastered concepts, gaps, and score.
    """
    # Verify course ownership
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.created_by == user.id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    if not body.questions:
        raise HTTPException(400, "questions list must not be empty")
    if not body.answers:
        raise HTTPException(400, "answers list must not be empty")

    # Get any provider (evaluate is CPU-only, no LLM call needed)
    try:
        provider = await model_router.get_provider(TaskType.MENTOR_CHAT)
    except Exception as e:
        raise HTTPException(500, f"No LLM provider available: {e}") from e

    service = DiagnosticService(provider)
    answers_dicts = [a.model_dump() for a in body.answers]
    diagnostic_result = service.evaluate(body.questions, answers_dicts)

    # Persist LearningRecord
    record = LearningRecord(
        user_id=user.id,
        course_id=course_id,
        type="diagnostic_complete",
        data={
            "score": diagnostic_result.score,
            "level": diagnostic_result.level,
            "mastered_concepts": diagnostic_result.mastered_concepts,
            "gaps": diagnostic_result.gaps,
            "question_count": len(body.questions),
            "answer_count": len(body.answers),
        },
    )
    db.add(record)
    # Commit happens automatically via get_db dependency on successful return

    return diagnostic_result
