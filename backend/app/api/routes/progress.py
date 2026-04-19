import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.db.models import Section, SectionProgress, User

router = APIRouter(prefix="/api/v1", tags=["progress"])


class SectionProgressResponse(BaseModel):
    section_id: uuid.UUID
    lesson_read: bool
    lab_completed: bool
    exercise_best_score: float | None
    status: str


class ProgressEventRequest(BaseModel):
    event: str


def _compute_status(p: SectionProgress) -> str:
    if p.lesson_read and p.exercise_best_score is not None and p.exercise_best_score >= 60.0:
        return "completed"
    if p.lesson_read or p.lab_completed or p.exercise_best_score is not None:
        return "in_progress"
    return "not_started"


@router.get("/courses/{course_id}/progress")
async def get_course_progress(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_local_user),
) -> list[SectionProgressResponse]:
    section_ids = (await db.execute(
        select(Section.id).where(Section.course_id == course_id)
    )).scalars().all()

    rows = (await db.execute(
        select(SectionProgress).where(
            SectionProgress.user_id == user.id,
            SectionProgress.section_id.in_(section_ids),
        )
    )).scalars().all()

    progress_map = {r.section_id: r for r in rows}
    result = []
    for sid in section_ids:
        if sid in progress_map:
            p = progress_map[sid]
            result.append(SectionProgressResponse(
                section_id=sid, lesson_read=p.lesson_read, lab_completed=p.lab_completed,
                exercise_best_score=p.exercise_best_score, status=_compute_status(p),
            ))
        else:
            result.append(SectionProgressResponse(
                section_id=sid, lesson_read=False, lab_completed=False,
                exercise_best_score=None, status="not_started",
            ))
    return result


@router.post("/sections/{section_id}/progress")
async def record_progress(
    section_id: uuid.UUID,
    req: ProgressEventRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_local_user),
):
    row = (await db.execute(
        select(SectionProgress).where(
            SectionProgress.user_id == user.id,
            SectionProgress.section_id == section_id,
        )
    )).scalar_one_or_none()

    if not row:
        row = SectionProgress(user_id=user.id, section_id=section_id)
        db.add(row)

    if req.event == "lesson_read":
        row.lesson_read = True
    elif req.event == "lab_completed":
        row.lab_completed = True

    await db.commit()
    return {"ok": True}
