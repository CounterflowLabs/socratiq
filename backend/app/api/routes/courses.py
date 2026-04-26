"""API routes for course management."""

import uuid
from collections import defaultdict
from math import inf
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.models.course import (
    CourseGenerateRequest,
    CourseResponse,
    CourseDetailResponse,
    CourseListResponse,
    RegenerateCourseRequest,
    RegenerateCourseResponse,
    SectionResponse,
    SourceSummary,
)
from app.services.course_generator import CourseGenerator
from app.services.cost_guard import CostGuard
from app.services.llm.router import ModelRouter

from app.db.models.user import User

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])

_MAX_VERSION_DEPTH = 64


async def _compute_version_index(db: AsyncSession, course: Course) -> int:
    """Return 1-indexed version number by walking the ``parent_id`` chain."""
    index = 1
    parent_id = course.parent_id
    visited: set[uuid.UUID] = {course.id}
    while parent_id is not None and index < _MAX_VERSION_DEPTH:
        if parent_id in visited:
            break
        visited.add(parent_id)
        index += 1
        row = (
            await db.execute(
                select(Course.parent_id).where(Course.id == parent_id)
            )
        ).first()
        if row is None:
            break
        parent_id = row[0]
    return index


def _extract_page_indices(metadata: dict[str, Any]) -> list[int]:
    """Read explicit page indices from source metadata when available."""
    for key in ("lesson_by_page", "graph_by_page", "labs_by_page"):
        raw_pages = metadata.get(key)
        if not isinstance(raw_pages, dict):
            continue

        page_indices: list[int] = []
        for page_key in raw_pages.keys():
            try:
                page_indices.append(int(page_key))
            except (TypeError, ValueError):
                continue

        deduped = sorted(set(page_indices))
        if deduped:
            return deduped

    return []


@router.post("/generate", response_model=CourseResponse, status_code=201)
async def generate_course(
    request: CourseGenerateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> CourseResponse:
    """Generate a course from one or more ingested sources."""
    from app.services.profile import load_profile

    profile = await load_profile(db, user.id)
    generator = CourseGenerator(model_router)
    try:
        course = await generator.generate(
            db=db,
            source_ids=request.source_ids,
            title=request.title,
            user_id=user.id,
            target_language=profile.preferred_language,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    version_index = await _compute_version_index(db, course)
    return CourseResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        parent_id=course.parent_id,
        regeneration_directive=course.regeneration_directive,
        version_index=version_index,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.get("", response_model=CourseListResponse)
async def list_courses(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    skip: int = 0,
    limit: int = 20,
) -> CourseListResponse:
    """List all courses with pagination."""
    result = await db.execute(
        select(Course)
        .where(Course.created_by == user.id)
        .order_by(Course.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    courses = result.scalars().all()

    total = (await db.execute(
        select(func.count()).select_from(Course).where(Course.created_by == user.id)
    )).scalar()

    items: list[CourseResponse] = []
    for c in courses:
        version_index = await _compute_version_index(db, c)
        items.append(
            CourseResponse(
                id=c.id,
                title=c.title,
                description=c.description,
                parent_id=c.parent_id,
                regeneration_directive=c.regeneration_directive,
                version_index=version_index,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return CourseListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{course_id}", response_model=CourseDetailResponse)
async def get_course(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> CourseDetailResponse:
    """Get a course with its sections."""
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.created_by == user.id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    result = await db.execute(
        select(Section)
        .where(Section.course_id == course_id)
        .order_by(Section.order_index)
    )
    sections = result.scalars().all()

    source_rows = (await db.execute(
        select(Source.id, Source.url, Source.type, Source.metadata_)
        .join(CourseSource, CourseSource.source_id == Source.id)
        .where(CourseSource.course_id == course.id)
    )).all()

    source_first_section_order: dict[uuid.UUID, int] = {}
    sections_by_source: dict[uuid.UUID, list[Section]] = defaultdict(list)
    for index, section in enumerate(sections):
        if not section.source_id:
            continue
        sections_by_source[section.source_id].append(section)
        source_first_section_order.setdefault(section.source_id, index)

    ordered_source_rows = sorted(
        source_rows,
        key=lambda row: (
            source_first_section_order.get(row.id, inf),
            str(row.id),
        ),
    )
    sources = [SourceSummary(id=r.id, url=r.url, type=r.type) for r in ordered_source_rows]

    source_page_index_by_section: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for row in ordered_source_rows:
        page_indices = _extract_page_indices(row.metadata_ or {})
        source_sections = sections_by_source.get(row.id, [])
        if len(page_indices) <= 1 or len(source_sections) != len(page_indices):
            continue

        source_page_index_by_section[row.id] = {
            section.id: page_index
            for section, page_index in zip(source_sections, page_indices, strict=False)
        }

    version_index = await _compute_version_index(db, course)
    return CourseDetailResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        parent_id=course.parent_id,
        regeneration_directive=course.regeneration_directive,
        version_index=version_index,
        sources=sources,
        sections=[
            SectionResponse(
                id=s.id,
                title=s.title,
                order_index=s.order_index,
                source_start=s.source_start,
                source_end=s.source_end,
                source_id=s.source_id,
                content={
                    **(s.content or {}),
                    **(
                        {"page_index": source_page_index_by_section[s.source_id][s.id]}
                        if s.source_id in source_page_index_by_section
                        and s.id in source_page_index_by_section[s.source_id]
                        else {}
                    ),
                },
                difficulty=s.difficulty,
            )
            for s in sections
        ],
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.post(
    "/{course_id}/regenerate",
    response_model=RegenerateCourseResponse,
    status_code=202,
)
async def regenerate_course_endpoint(
    course_id: uuid.UUID,
    request: RegenerateCourseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> RegenerateCourseResponse:
    """Kick off a regeneration of an existing course.

    Creates a new ``Course`` row whose ``parent_id`` points at the supplied
    ``course_id``. Pipeline runs from the source's already-extracted chunks; the
    optional ``directive`` is injected into content_analysis, lesson_generation,
    and lab_generation prompts.
    """
    course = (await db.execute(
        select(Course).where(Course.id == course_id, Course.created_by == user.id)
    )).scalar_one_or_none()
    if course is None:
        raise HTTPException(404, f"Course {course_id} not found")

    linked_sources = (await db.execute(
        select(Source)
        .join(CourseSource, CourseSource.source_id == Source.id)
        .where(CourseSource.course_id == course.id)
    )).scalars().all()
    if not linked_sources:
        raise HTTPException(400, "Course has no linked sources to regenerate")
    for s in linked_sources:
        if s.status != "ready":
            raise HTTPException(
                400,
                f"Source {s.id} is not ready (status={s.status}); cannot regenerate",
            )

    cost_guard = CostGuard(db)
    if not await cost_guard.check_budget(user.id, "course_regeneration"):
        raise HTTPException(
            429, "Daily LLM budget exceeded for course regeneration."
        )

    from app.worker.tasks.course_regeneration import regenerate_course

    directive = (request.directive or "").strip()
    celery_task = regenerate_course.delay(
        str(course.id), directive, str(user.id)
    )

    return RegenerateCourseResponse(
        task_id=celery_task.id,
        parent_course_id=course.id,
    )


@router.get("/regenerations/{task_id}")
async def get_regeneration_status(
    task_id: str,
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Poll the status of a regeneration task.

    Returns ``{status, stage, course_id?, error?}``. Frontend polls this every
    few seconds until ``status`` is ``success`` or ``failure``.
    """
    from celery.result import AsyncResult

    from app.worker.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    state = result.state

    payload: dict = {"status": state.lower(), "stage": None}
    info = result.info if result.info is not None else {}
    if isinstance(info, dict):
        payload["stage"] = info.get("stage")

    if state == "SUCCESS":
        payload["status"] = "success"
        if isinstance(result.result, dict):
            payload["course_id"] = result.result.get("course_id")
            payload["parent_course_id"] = result.result.get("parent_course_id")
    elif state == "FAILURE":
        payload["status"] = "failure"
        payload["error"] = str(result.result) if result.result else "Unknown error"
    elif state == "PROGRESS":
        payload["status"] = "running"
    elif state == "PENDING":
        payload["status"] = "pending"

    return payload
