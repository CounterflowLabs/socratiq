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
    SectionResponse,
    SourceSummary,
)
from app.services.course_generator import CourseGenerator
from app.services.llm.router import ModelRouter

from app.db.models.user import User

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


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
    generator = CourseGenerator(model_router)
    try:
        course = await generator.generate(
            db=db,
            source_ids=request.source_ids,
            title=request.title,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return CourseResponse(
        id=course.id,
        title=course.title,
        description=course.description,
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

    return CourseListResponse(
        items=[
            CourseResponse(
                id=c.id,
                title=c.title,
                description=c.description,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in courses
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


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

    return CourseDetailResponse(
        id=course.id,
        title=course.title,
        description=course.description,
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
