"""API routes for course management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.course import Course, CourseSource, Section
from app.models.course import (
    CourseGenerateRequest,
    CourseResponse,
    CourseDetailResponse,
    CourseListResponse,
    SectionResponse,
)
from app.services.course_generator import CourseGenerator
from app.services.llm.router import ModelRouter

from app.db.models.user import User

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


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

    cs_result = await db.execute(
        select(CourseSource.source_id).where(CourseSource.course_id == course_id)
    )
    source_ids = [row[0] for row in cs_result.all()]

    return CourseDetailResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        source_ids=source_ids,
        sections=[
            SectionResponse(
                id=s.id,
                title=s.title,
                order_index=s.order_index,
                source_start=s.source_start,
                source_end=s.source_end,
                content=s.content,
                difficulty=s.difficulty,
            )
            for s in sections
        ],
        created_at=course.created_at,
        updated_at=course.updated_at,
    )
