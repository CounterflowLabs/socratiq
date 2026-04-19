"""API routes for content source management."""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.course import Course, CourseSource
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.db.models.user import User
from app.models.source import SourceListResponse, SourceResponse, SourceTaskSummary
from app.services.content_key import extract_content_key
from app.services.source_tasks import create_source_task
from app.worker.tasks.content_ingestion import ingest_source, clone_source

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

_ACTIVE_SOURCE_STATUSES = {
    "pending",
    "processing",
    "extracting",
    "analyzing",
    "generating_lessons",
    "generating_labs",
    "storing",
    "embedding",
}
_ACTIVE_TASK_STATUSES = {"pending", "running", "progress"}
_ACTIONABLE_RANK = {"failure": 0, "processing": 1, "ready": 2}

@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SourceResponse:
    """Submit a URL or upload a file for content ingestion."""
    if not url and not file:
        raise HTTPException(400, "Either 'url' or 'file' must be provided")

    metadata: dict = {}
    file_content: bytes | None = None

    if file:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are supported")

        source_type = "pdf"
        title = title or file.filename

        upload_dir = Path(get_settings().upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_id = str(uuid.uuid4())
        file_path = upload_dir / f"{file_id}.pdf"

        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:
            raise HTTPException(413, "File too large (max 50MB)")
        file_path.write_bytes(file_content)

        metadata = {
            "file_path": str(file_path.resolve()),
            "original_filename": file.filename,
            "file_size": len(file_content),
        }
    else:
        if not source_type:
            source_type = _detect_source_type(url)
        if source_type not in ("bilibili", "youtube"):
            raise HTTPException(400, f"Unsupported source type: {source_type}")

    content_key = extract_content_key(
        source_type=source_type,
        url=url,
        file_content=file_content,
    )

    if content_key:
        active_result = await db.execute(
            select(Source)
            .where(
                Source.created_by == user.id,
                Source.content_key == content_key,
                Source.status.in_(
                    ["pending", "extracting", "analyzing", "generating_lessons", "generating_labs", "storing", "embedding"]
                ),
            )
            .order_by(Source.created_at.desc())
            .limit(1)
        )
        active_source = active_result.scalar_one_or_none()
        if active_source and active_source.celery_task_id:
            return await _source_to_response(db, active_source, user_id=user.id)

        ready_result = await db.execute(
            select(Source)
            .where(
                Source.created_by == user.id,
                Source.content_key == content_key,
                Source.status == "ready",
            )
            .order_by(Source.created_at.desc())
            .limit(1)
        )
        donor_source = ready_result.scalar_one_or_none()
        if donor_source:
            source = Source(
                type=source_type,
                url=url,
                title=title,
                status="pending",
                metadata_={**metadata, "reused_existing_source": True},
                content_key=content_key,
                ref_source_id=donor_source.id,
                created_by=user.id,
            )
            db.add(source)
            await db.flush()

            task = clone_source.delay(str(source.id), str(donor_source.id))
            source.celery_task_id = task.id
            await create_source_task(
                db,
                source_id=source.id,
                task_type="source_processing",
                status="pending",
                celery_task_id=task.id,
            )
            await db.commit()
            await db.refresh(source)
            return await _source_to_response(db, source, user_id=user.id)

    source = Source(
        type=source_type,
        url=url,
        title=title,
        status="pending",
        metadata_=metadata,
        content_key=content_key,
        created_by=user.id,
    )
    db.add(source)
    await db.flush()

    task = ingest_source.delay(str(source.id))
    source.celery_task_id = task.id
    await create_source_task(
        db,
        source_id=source.id,
        task_type="source_processing",
        status="pending",
        celery_task_id=task.id,
    )
    await db.commit()
    await db.refresh(source)

    return await _source_to_response(db, source, user_id=user.id)


@router.get("", response_model=SourceListResponse)
async def list_sources(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    query: str | None = None,
    status: Literal["all", "processing", "ready", "failure"] = "all",
    source_type: str | None = None,
    sort: Literal["actionable", "recent"] = "recent",
    skip: int = 0,
    limit: int = 20,
) -> SourceListResponse:
    """List all content sources with filtering, sorting, and pagination."""
    base_query = _build_source_base_query(
        user_id=user.id,
        query=query,
        source_type=source_type,
    )

    if sort == "recent" and status == "all":
        count_result = await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        page_result = await db.execute(
            base_query.order_by(Source.created_at.desc()).offset(skip).limit(limit)
        )
        page_sources = page_result.scalars().all()
        if not page_sources:
            return SourceListResponse(items=[], total=total, skip=skip, limit=limit)

        source_ids = [source.id for source in page_sources]
        latest_task_summaries = await _get_latest_task_summaries(db, source_ids)
        course_summaries = await _get_course_summaries(db, source_ids, user_id=user.id)
        page_items = [
            await _source_to_response(
                db,
                source,
                user_id=user.id,
                latest_processing_task=latest_task_summaries.get(source.id, {}).get(
                    "source_processing"
                ),
                latest_course_task=latest_task_summaries.get(source.id, {}).get(
                    "course_generation"
                ),
                course_count=course_summaries.get(source.id, (0, None))[0],
                latest_course_id=course_summaries.get(source.id, (0, None))[1],
            )
            for source in page_sources
        ]

        return SourceListResponse(
            items=page_items,
            total=total,
            skip=skip,
            limit=limit,
        )

    result = await db.execute(base_query.order_by(Source.created_at.desc()))
    sources = result.scalars().all()

    if not sources:
        return SourceListResponse(items=[], total=0, skip=skip, limit=limit)

    source_ids = [source.id for source in sources]
    latest_task_summaries = await _get_latest_task_summaries(db, source_ids)
    course_summaries = await _get_course_summaries(db, source_ids, user_id=user.id)

    items_with_meta: list[tuple[str, SourceResponse, object]] = []
    for source in sources:
        task_summaries = latest_task_summaries.get(source.id, {})
        latest_processing_task = task_summaries.get("source_processing")
        latest_course_task = task_summaries.get("course_generation")
        course_count, latest_course_id = course_summaries.get(source.id, (0, None))
        material_status = _source_material_status(
            source,
            latest_processing_task=latest_processing_task,
            latest_course_task=latest_course_task,
        )

        if status != "all" and material_status != status:
            continue

        items_with_meta.append((
            material_status,
            await _source_to_response(
                db,
                source,
                user_id=user.id,
                latest_processing_task=latest_processing_task,
                latest_course_task=latest_course_task,
                course_count=course_count,
                latest_course_id=latest_course_id,
            ),
            source.created_at,
        ))

    if sort == "actionable":
        items_with_meta.sort(key=lambda item: item[2], reverse=True)
        items_with_meta.sort(key=lambda item: _ACTIONABLE_RANK[item[0]])
    else:
        items_with_meta.sort(key=lambda item: item[2], reverse=True)

    total = len(items_with_meta)
    page_items = [item[1] for item in items_with_meta[skip : skip + limit]]

    return SourceListResponse(
        items=page_items,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SourceResponse:
    """Get a single source by ID."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.created_by == user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")
    return await _source_to_response(db, source, user_id=user.id)


@router.get("/{source_id}/file")
async def get_source_file(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> FileResponse:
    """Serve an uploaded PDF file for the owning user."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.created_by == user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")
    if source.type != "pdf":
        raise HTTPException(400, "Only uploaded PDF sources can be downloaded")

    file_path_value = (source.metadata_ or {}).get("file_path")
    if not file_path_value:
        raise HTTPException(400, "This PDF source does not have a local file")

    file_path = Path(file_path_value)
    if not file_path.is_file():
        raise HTTPException(404, "Source file not found")

    filename = (
        (source.metadata_ or {}).get("original_filename")
        or source.title
        or f"{source.id}.pdf"
    )
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
    )


def _detect_source_type(url: str | None) -> str:
    if not url:
        raise HTTPException(400, "URL is required for non-file sources")
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    raise HTTPException(400, f"Cannot detect source type from URL: {url}")


async def _get_latest_task_summary(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    task_type: str,
) -> SourceTaskSummary | None:
    result = await db.execute(
        select(SourceTask)
        .where(
            SourceTask.source_id == source_id,
            SourceTask.task_type == task_type,
        )
        .order_by(SourceTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None

    return SourceTaskSummary(
        task_type=task.task_type,
        status=task.status,
        stage=task.stage,
        error_summary=task.error_summary,
        celery_task_id=task.celery_task_id,
    )


async def _get_latest_task_summaries(
    db: AsyncSession,
    source_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, SourceTaskSummary]]:
    if not source_ids:
        return {}

    result = await db.execute(
        select(SourceTask)
        .where(SourceTask.source_id.in_(source_ids))
        .order_by(
            SourceTask.source_id,
            SourceTask.task_type,
            SourceTask.created_at.desc(),
            SourceTask.id.desc(),
        )
    )

    latest: dict[uuid.UUID, dict[str, SourceTaskSummary]] = {}
    seen: set[tuple[uuid.UUID, str]] = set()
    for task in result.scalars():
        key = (task.source_id, task.task_type)
        if key in seen:
            continue
        seen.add(key)
        latest.setdefault(task.source_id, {})[task.task_type] = SourceTaskSummary(
            task_type=task.task_type,
            status=task.status,
            stage=task.stage,
            error_summary=task.error_summary,
            celery_task_id=task.celery_task_id,
        )
    return latest


async def _get_course_summaries(
    db: AsyncSession,
    source_ids: list[uuid.UUID],
    *,
    user_id: uuid.UUID,
) -> dict[uuid.UUID, tuple[int, uuid.UUID | None]]:
    if not source_ids:
        return {}

    result = await db.execute(
        select(CourseSource.source_id, CourseSource.course_id)
        .join(Course, Course.id == CourseSource.course_id)
        .where(
            CourseSource.source_id.in_(source_ids),
            Course.created_by == user_id,
        )
        .order_by(
            CourseSource.source_id,
            Course.created_at.desc(),
            CourseSource.course_id.desc(),
        )
    )

    summaries: dict[uuid.UUID, tuple[int, uuid.UUID | None]] = {}
    latest_seen: set[uuid.UUID] = set()
    for source_id, course_id in result.all():
        count, latest_course_id = summaries.get(source_id, (0, None))
        if source_id not in latest_seen:
            latest_course_id = course_id
            latest_seen.add(source_id)
        summaries[source_id] = (count + 1, latest_course_id)
    return summaries


async def _source_to_response(
    db: AsyncSession,
    source: Source,
    *,
    user_id: uuid.UUID,
    latest_processing_task: SourceTaskSummary | None = None,
    latest_course_task: SourceTaskSummary | None = None,
    course_count: int | None = None,
    latest_course_id: uuid.UUID | None = None,
) -> SourceResponse:
    if latest_processing_task is None:
        latest_processing_task = await _get_latest_task_summary(
            db,
            source_id=source.id,
            task_type="source_processing",
        )
    if latest_course_task is None:
        latest_course_task = await _get_latest_task_summary(
            db,
            source_id=source.id,
            task_type="course_generation",
        )
    if course_count is None or latest_course_id is None:
        course_count, latest_course_id = (
            await _get_course_summaries(db, [source.id], user_id=user_id)
        ).get(source.id, (0, None))

    return SourceResponse(
        id=source.id,
        type=source.type,
        url=source.url,
        title=source.title,
        status=source.status,
        metadata_=source.metadata_,
        task_id=source.celery_task_id,
        latest_processing_task=latest_processing_task,
        latest_course_task=latest_course_task,
        course_count=course_count,
        latest_course_id=latest_course_id,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _build_source_base_query(
    *,
    user_id: uuid.UUID,
    query: str | None,
    source_type: str | None,
):
    filters = [Source.created_by == user_id]

    if query:
        pattern = f"%{query}%"
        original_filename = Source.metadata_["original_filename"].as_string()
        filters.append(
            or_(
                Source.title.ilike(pattern),
                Source.url.ilike(pattern),
                func.coalesce(original_filename, "").ilike(pattern),
            )
        )

    if source_type:
        filters.append(Source.type == source_type)

    return select(Source).where(*filters)


def _source_material_status(
    source: Source,
    *,
    latest_processing_task: SourceTaskSummary | None,
    latest_course_task: SourceTaskSummary | None,
) -> str:
    if source.status == "error":
        return "failure"

    tasks = [task for task in (latest_processing_task, latest_course_task) if task]
    if any(task.status == "failure" for task in tasks):
        return "failure"

    if source.status in _ACTIVE_SOURCE_STATUSES or any(
        task.status in _ACTIVE_TASK_STATUSES for task in tasks
    ):
        return "processing"

    return "ready"
