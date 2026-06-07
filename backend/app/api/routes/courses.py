"""API routes for course management."""

import uuid
from collections import defaultdict
from datetime import datetime
from math import inf
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user, get_model_router
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.models.source import SourceTaskProgress
from app.worker.queue import abort_job, enqueue, get_job_state
from app.models.course import (
    CourseGenerateRequest,
    CourseGenerateResponse,
    CourseProgressResponse,
    CourseResponse,
    CourseDetailResponse,
    CourseListResponse,
    RegenerateCourseRequest,
    RegenerateCourseResponse,
    RegenerateSectionLessonResponse,
    SectionMergeResponse,
    SectionResponse,
    SectionSplitRequest,
    SectionSplitResponse,
    SourceSummary,
)
from app.services.course_generator import CourseGenerator
from app.services.cost_guard import CostGuard
from app.services.llm.router import ModelRouter

from app.db.models.user import User

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])

_MAX_VERSION_DEPTH = 64


class PromptCourseRequest(BaseModel):
    """Request body for generating a course from a single one-sentence prompt.

    Unlike ``/generate`` (which derives a course from already-ingested
    sources), this path has NO source material — the outline and every lesson
    are produced from the LLM's own topic knowledge, guided only by ``prompt``.
    """

    prompt: str = Field(..., min_length=1, max_length=2000)
    target_language: str = "zh-CN"


class PromptCourseResponse(BaseModel):
    """202 response from POST /courses/from-prompt."""

    task_id: str
    status: str  # "dispatched"


async def _compute_version_index(db: AsyncSession, course: Course) -> int:
    """Return 1-indexed version number within the course's family tree.

    The family tree is rooted at the topmost ancestor; the version index is the
    course's chronological position (by ``created_at``) among all descendants
    of that root plus the root itself. This is robust to branching — multiple
    regenerations of the same parent become v2, v3, v4 in order, rather than
    all collapsing to v2.
    """
    # 1. Walk up to find the root course.
    root = course
    visited: set[uuid.UUID] = {course.id}
    steps = 0
    while root.parent_id is not None and steps < _MAX_VERSION_DEPTH:
        parent = await db.get(Course, root.parent_id)
        if parent is None or parent.id in visited:
            break
        visited.add(parent.id)
        root = parent
        steps += 1

    # 2. Walk descendants from the root and rank by created_at. This avoids
    # raw recursive SQL here, which is brittle across test DB drivers when UUID
    # bind parameters are inferred as text.
    family: list[tuple[int, Course]] = [(0, root)]
    frontier = [root.id]
    seen: set[uuid.UUID] = {root.id}
    steps = 0
    while frontier and steps < _MAX_VERSION_DEPTH:
        rows = (
            await db.execute(select(Course).where(Course.parent_id.in_(frontier)))
        ).scalars().all()
        frontier = []
        for child in rows:
            if child.id in seen:
                continue
            seen.add(child.id)
            family.append((steps + 1, child))
            frontier.append(child.id)
        steps += 1

    ranked = sorted(
        family,
        key=lambda item: (item[0], item[1].created_at or datetime.min, str(item[1].id)),
    )
    for index, (_depth, item) in enumerate(ranked, start=1):
        if item.id == course.id:
            return index
    return 1


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


@router.post(
    "/generate",
    response_model=CourseGenerateResponse,
    status_code=202,
)
async def generate_course(
    request: CourseGenerateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> CourseGenerateResponse:
    """Asynchronously synthesize a single course from one or more sources.

    PRD §5.4 — replaces the legacy synchronous variant (which blocked the
    request thread for minutes) with a dispatch endpoint that returns a
    task id. Progress is tracked through the unified ``/api/v1/tasks``
    queue; the resulting ``course_id`` shows up on the per-source task row
    once generation completes.
    """
    from uuid import uuid4

    from app.db.models.source_task import SourceTask
    from app.services.source_tasks import create_source_task

    sources = (
        await db.execute(
            select(Source).where(
                Source.id.in_(request.source_ids),
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalars().all()
    if len(sources) != len(request.source_ids):
        raise HTTPException(
            404,
            f"Not all sources are accessible: requested {len(request.source_ids)}, "
            f"found {len(sources)}",
        )
    for s in sources:
        if s.status != "ready":
            raise HTTPException(
                409,
                f"Source {s.id} is {s.status!r}; only ready sources can generate a course",
            )

    # If any anchor source already has a pending/running course_generation
    # task, surface that instead of spawning a duplicate.
    existing = (
        await db.execute(
            select(SourceTask)
            .where(
                SourceTask.source_id.in_(request.source_ids),
                SourceTask.task_type == "course_generation",
                SourceTask.status.in_(("pending", "running")),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CourseGenerateResponse(
            task_id=existing.celery_task_id or str(existing.id),
            source_ids=request.source_ids,
            status="already_dispatched",
        )

    task_id = str(uuid4())
    config = {
        "brief": request.brief,
        "depth": request.depth,
        "audience": request.audience,
        "tier": request.tier,
        "language": request.language,
        "includes": request.includes.model_dump(),
        "source_weights": (
            {str(k): float(v) for k, v in request.source_weights.items()}
            if request.source_weights
            else None
        ),
    }
    # One source_tasks row per source so the unified Tasks queue surfaces
    # the work against every contributor. The anchor row carries the
    # celery_task_id; the rest reference the same task in metadata so the
    # cancel/retry endpoints can find the whole cohort.
    anchor_id = request.source_ids[0]
    for sid in request.source_ids:
        await create_source_task(
            db,
            source_id=sid,
            task_type="course_generation",
            celery_task_id=task_id if sid == anchor_id else None,
            status="pending",
            stage="pending",
            metadata_={
                "source_ids": [str(s) for s in request.source_ids],
                "anchor_source_id": str(anchor_id),
                "config": config,
                "title": request.title,
            },
        )
    await db.commit()

    await enqueue(
        "generate_multi",
        {
            "source_ids": [str(s) for s in request.source_ids],
            "title": request.title,
            "config": config,
        },
        user_id=str(user.id),
        job_id=task_id,
    )

    return CourseGenerateResponse(
        task_id=task_id,
        source_ids=request.source_ids,
        status="dispatched",
    )


@router.post(
    "/from-prompt",
    response_model=PromptCourseResponse,
    status_code=202,
)
async def generate_course_from_prompt(
    request: PromptCourseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> PromptCourseResponse:
    """Generate a full course from a single one-sentence prompt (source-less).

    Enqueues ``generate_sentence_course`` which explores + freezes an outline
    from the prompt, then fills each section with a lesson drawn from the LLM's
    own topic knowledge (there is no source material). Returns the task id;
    progress streams over the AG-UI run keyed by that id, and the course
    surfaces in ``GET /courses`` once generation completes.
    """
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(422, "prompt must not be empty")

    job_id = await enqueue(
        "generate_sentence_course",
        prompt,
        str(user.id),
        request.target_language,
    )

    return PromptCourseResponse(
        task_id=job_id or "",
        status="dispatched",
    )


@router.get("/runs/{run_id}/events")
async def stream_course_run_events(
    run_id: str,
    user: Annotated[User, Depends(get_local_user)],
):
    """Source-less AG-UI event stream for a course-generation run.

    Mirrors the source-scoped ``GET /sources/{id}/runs/{run_id}/events`` but for
    runs with no source (``from-prompt`` sentence→course). The ARQ worker
    publishes the run's AG-UI events to a Redis stream keyed by ``run_id``; we
    subscribe and re-emit them as SSE. The terminal ``RUN_FINISHED`` event
    carries ``result.course_id`` so the client can navigate to the new course.

    Auth is by authenticated user only — there is no source to scope ownership
    to, and ``run_id`` is an unguessable ARQ job id (single-tenant local model).
    """
    import redis.asyncio as aioredis

    from app.agentcore.events import RedisEventSink
    from app.config import get_settings

    redis = aioredis.from_url(get_settings().redis_url)

    async def event_stream():
        try:
            async for body in RedisEventSink.subscribe(redis, run_id):
                yield f"data: {body}\n\n"
        finally:
            await redis.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/generate-sync",
    response_model=CourseResponse,
    deprecated=True,
    status_code=201,
)
async def generate_course_sync(
    request: CourseGenerateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> CourseResponse:
    """Synchronous legacy entry point — kept for older callers.

    New callers should use ``POST /courses/generate`` which is now
    asynchronous and accepts the §5.4 config.
    """
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
        active_regeneration_task_id=course.active_regeneration_task_id,
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

    if course.active_regeneration_task_id:
        if await get_job_state(course.active_regeneration_task_id) in {"pending", "running"}:
            return RegenerateCourseResponse(
                task_id=course.active_regeneration_task_id,
                parent_course_id=course.id,
            )

    cost_guard = CostGuard(db)
    if not await cost_guard.check_budget(user.id, "course_regeneration"):
        raise HTTPException(
            429, "Daily LLM budget exceeded for course regeneration."
        )

    directive = (request.directive or "").strip()
    job_id = await enqueue(
        "regenerate_course", str(course.id), directive, str(user.id)
    )
    course.active_regeneration_task_id = job_id
    await db.commit()

    return RegenerateCourseResponse(
        task_id=job_id,
        parent_course_id=course.id,
    )


@router.delete(
    "/{course_id}/regeneration",
    status_code=204,
)
async def clear_regeneration(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> None:
    """Drop the cached regeneration task pointer on a course.

    Frontend calls this after the user dismisses a finalized banner or
    navigates to the new version. POST /regenerate will start a fresh
    task on the next click.
    """
    course = (await db.execute(
        select(Course).where(Course.id == course_id, Course.created_by == user.id)
    )).scalar_one_or_none()
    if course is None:
        raise HTTPException(404, f"Course {course_id} not found")
    course.active_regeneration_task_id = None
    await db.commit()


@router.post("/{course_id}/regeneration/cancel", status_code=202)
async def cancel_regeneration(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Request cooperative cancellation of an in-flight regeneration."""
    course = (
        await db.execute(
            select(Course).where(Course.id == course_id, Course.created_by == user.id)
        )
    ).scalar_one_or_none()
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    if not course.active_regeneration_task_id:
        return {"cancelled": False, "course_id": str(course_id)}

    # Flag every linked source's course_regeneration row.
    source_ids = (
        await db.execute(
            select(CourseSource.source_id).where(CourseSource.course_id == course_id)
        )
    ).scalars().all()

    rows = (
        await db.execute(
            select(SourceTask).where(
                SourceTask.source_id.in_(source_ids) if source_ids else False,
                SourceTask.task_type == "course_regeneration",
                SourceTask.status.in_(("pending", "running")),
            )
        )
    ).scalars().all()
    for row in rows:
        row.cancel_requested = True

    await abort_job(course.active_regeneration_task_id)

    await db.commit()
    return {"cancelled": True, "course_id": str(course_id)}


@router.get("/regenerations/{task_id}", deprecated=True)
async def get_regeneration_status(
    task_id: str,
    user: Annotated[User, Depends(get_local_user)],
    response: Response,
) -> dict:
    """Deprecated. Use ``GET /courses/{course_id}/task-progress`` instead.

    Reads from Celery's result backend, which has a TTL — once the result
    expires this endpoint cannot distinguish "expired success" from "never
    queued". The DB-backed progress endpoint is authoritative.
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 09 Jun 2026 00:00:00 GMT"
    response.headers["Link"] = (
        '</api/v1/courses/{course_id}/task-progress>; rel="successor-version"'
    )

    # Transport-level job state only; authoritative progress/result live in the
    # SourceTask rows surfaced by GET /courses/{course_id}/task-progress.
    return {"status": await get_job_state(task_id), "stage": None}


@router.get("/{course_id}/task-progress", response_model=CourseProgressResponse)
async def get_course_task_progress(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> CourseProgressResponse:
    """Aggregate progress for a course's generation and regeneration tasks.

    DB-authoritative. Pulls the latest SourceTask row per relevant task_type
    across all sources linked to this course.
    """
    course = (
        await db.execute(
            select(Course).where(
                Course.id == course_id, Course.created_by == user.id
            )
        )
    ).scalar_one_or_none()
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    source_ids = (
        await db.execute(
            select(CourseSource.source_id).where(
                CourseSource.course_id == course_id
            )
        )
    ).scalars().all()

    rows: list[SourceTask] = []
    if source_ids:
        rows = (
            await db.execute(
                select(SourceTask)
                .where(
                    SourceTask.source_id.in_(source_ids),
                    SourceTask.task_type.in_(
                        ("course_generation", "course_regeneration")
                    ),
                )
                .order_by(SourceTask.created_at.desc())
            )
        ).scalars().all()

    tasks = [
        SourceTaskProgress(
            task_type=t.task_type,
            status=t.status,
            stage=t.stage,
            error_summary=t.error_summary,
            celery_task_id=t.celery_task_id,
            metadata_=t.metadata_ or {},
            cancel_requested=t.cancel_requested,
            course_id=(
                uuid.UUID(t.metadata_["course_id"])
                if isinstance(t.metadata_, dict) and t.metadata_.get("course_id")
                else None
            ),
            updated_at=t.updated_at,
            created_at=t.created_at,
        )
        for t in rows
    ]

    return CourseProgressResponse(
        course_id=course.id,
        parent_course_id=course.parent_id,
        active_regeneration_task_id=course.active_regeneration_task_id,
        tasks=tasks,
    )


@router.post(
    "/sections/{section_id}/regenerate-lesson",
    response_model=RegenerateSectionLessonResponse,
    status_code=202,
)
async def regenerate_section_lesson_endpoint(
    section_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> RegenerateSectionLessonResponse:
    """Retry lesson generation for one section.

    Used by the frontend when a section shows ``lesson_generation_error``.
    Per-section lock: at most one in-flight retry per section. The active
    task id is also returned so the UI can poll for completion.
    """
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(404, f"Section {section_id} not found")

    # Authorize: caller must own the course this section belongs to.
    course = await db.get(Course, section.course_id)
    if course is None or course.created_by != user.id:
        raise HTTPException(404, f"Section {section_id} not found")

    if section.active_lesson_task_id:
        if await get_job_state(section.active_lesson_task_id) in {"pending", "running"}:
            return RegenerateSectionLessonResponse(
                task_id=section.active_lesson_task_id,
                section_id=section_id,
                status="in_flight",
            )

    job_id = await enqueue(
        "regenerate_section_lesson", str(section_id), str(user.id)
    )
    section.active_lesson_task_id = job_id
    section.lesson_generation_error = None
    await db.commit()

    return RegenerateSectionLessonResponse(
        task_id=job_id,
        section_id=section_id,
        status="dispatched",
    )


@router.post(
    "/sections/{section_id}/merge-next",
    response_model=SectionMergeResponse,
)
async def merge_section_with_next_endpoint(
    section_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SectionMergeResponse:
    """Merge a section with the section immediately following it.

    Manual-override path from Phase 4 of section-planning.md. Chunks from the
    trailing section move into this one, the trailing section is deleted,
    and order_index is renumbered. Lesson content is left stale — caller can
    call ``/regenerate-lesson`` after if a fresh lesson is wanted.
    """
    from app.services.section_override import (
        CrossSourceMerge,
        NoAdjacentSection,
        SectionNotFound,
        SectionNotOwned,
        merge_with_next,
    )

    try:
        result = await merge_with_next(
            db, section_id=section_id, user_id=user.id
        )
    except SectionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except SectionNotOwned as exc:
        raise HTTPException(404, str(exc)) from exc
    except NoAdjacentSection as exc:
        raise HTTPException(409, str(exc)) from exc
    except CrossSourceMerge as exc:
        raise HTTPException(409, str(exc)) from exc

    await db.commit()
    return SectionMergeResponse(
        surviving_section_id=result.surviving_section_id,
        removed_section_id=result.removed_section_id,
        chunks_reassigned=result.chunks_reassigned,
    )


@router.post(
    "/sections/{section_id}/split",
    response_model=SectionSplitResponse,
)
async def split_section_endpoint(
    section_id: uuid.UUID,
    payload: SectionSplitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SectionSplitResponse:
    """Split a section into two at the given chunk index.

    Manual-override path from Phase 4 of section-planning.md. The original
    section keeps the first ``split_at_chunk_index`` chunks; the rest move
    to a newly-created section that slots in immediately after. order_index
    of every following section is bumped up by one to make room.
    """
    from app.services.section_override import (
        SectionNotFound,
        SectionNotOwned,
        SplitPositionInvalid,
        split_section,
    )

    try:
        result = await split_section(
            db,
            section_id=section_id,
            user_id=user.id,
            split_at_chunk_index=payload.split_at_chunk_index,
        )
    except SectionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except SectionNotOwned as exc:
        raise HTTPException(404, str(exc)) from exc
    except SplitPositionInvalid as exc:
        raise HTTPException(400, str(exc)) from exc

    await db.commit()
    return SectionSplitResponse(
        original_section_id=result.original_section_id,
        new_section_id=result.new_section_id,
        chunks_in_original=result.chunks_in_original,
        chunks_in_new=result.chunks_in_new,
    )
