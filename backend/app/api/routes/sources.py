"""API routes for content source management."""

import uuid
from pathlib import Path
from typing import Annotated, Literal

from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.db.models.user import User
from app.models.source import (
    SourceEmbed,
    SourceListResponse,
    SourceProgressResponse,
    SourceResponse,
    SourceTaskProgress,
    SourceTaskSummary,
)
from app.services.bilibili_credential import has_bilibili_credential
from app.services.content_key import extract_content_key
from app.services.source_tasks import create_source_task, dispatch_course_generation
from app.worker.queue import abort_job, enqueue

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
    "planning",
}
_ACTIVE_TASK_STATUSES = {"pending", "running", "progress"}
_ACTIONABLE_RANK = {"failure": 0, "processing": 1, "ready": 2}

@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    response: Response,
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
    ingest_options_json: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SourceResponse:
    """Submit a URL or upload a file for content ingestion."""
    if not url and not file:
        raise HTTPException(400, "Either 'url' or 'file' must be provided")

    metadata: dict = {}
    # Optional per-source ingest overrides (PRD §5.2): chunk size,
    # transcript source, OCR strategy. The pipeline reads these from
    # metadata.ingest_options when they're present; absence falls back
    # to global defaults so existing callers stay unaffected.
    if ingest_options_json:
        try:
            import json as _json

            opts = _json.loads(ingest_options_json)
            if isinstance(opts, dict):
                metadata["ingest_options"] = opts
        except Exception:
            raise HTTPException(400, "ingest_options_json is not valid JSON")
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
        existing_result = await db.execute(
            select(Source)
            .where(
                Source.created_by == user.id,
                Source.content_key == content_key,
                Source.status != "deleted",
            )
            .order_by(Source.created_at.desc())
            .limit(1)
        )
        existing_source = existing_result.scalar_one_or_none()
        if existing_source:
            response.status_code = 200
            return await _source_to_response(
                db,
                existing_source,
                user_id=user.id,
                duplicate_of_source_id=existing_source.id,
                duplicate_reason="user_existing",
            )

        reusable_result = await db.execute(
            select(Source)
            .where(
                Source.content_key == content_key,
                Source.status == "ready",
                or_(Source.created_by != user.id, Source.created_by.is_(None)),
            )
            .order_by(Source.created_at.desc())
            .limit(1)
        )
        donor_source = reusable_result.scalar_one_or_none()
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

            job_id = await enqueue("clone_source", str(source.id), str(donor_source.id))
            source.celery_task_id = job_id
            await create_source_task(
                db,
                source_id=source.id,
                task_type="source_processing",
                status="pending",
                celery_task_id=job_id,
            )
            await db.commit()
            await db.refresh(source)
            return await _source_to_response(
                db,
                source,
                user_id=user.id,
                duplicate_of_source_id=donor_source.id,
                duplicate_reason="global_existing_reused",
            )

    if source_type == "bilibili" and not await has_bilibili_credential(db):
        raise HTTPException(
            status_code=412,
            detail={
                "code": "bilibili_credential_required",
                "message": "导入 B 站视频需要先登录 B 站账号才能抓取字幕。",
            },
        )

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

    job_id = await enqueue("ingest_source", str(source.id))
    source.celery_task_id = job_id
    await create_source_task(
        db,
        source_id=source.id,
        task_type="source_processing",
        status="pending",
        celery_task_id=job_id,
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
        select(Source).where(
            Source.id == source_id,
            Source.created_by == user.id,
            Source.status != "deleted",
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")
    return await _source_to_response(db, source, user_id=user.id)


@router.post("/{source_id}/cancel", status_code=202)
async def cancel_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Request cooperative cancellation of any running tasks for this source.

    Sets ``cancel_requested=true`` on active SourceTask rows and revokes the
    Celery task without terminating (so workers exit cleanly at the next
    safe break point).
    """
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")

    rows = (
        await db.execute(
            select(SourceTask)
            .where(
                SourceTask.source_id == source_id,
                SourceTask.status.in_(("pending", "running")),
            )
        )
    ).scalars().all()

    if not rows:
        return {"cancelled": 0, "source_id": str(source_id)}

    for row in rows:
        row.cancel_requested = True
        if row.celery_task_id:
            await abort_job(row.celery_task_id)
    await db.commit()
    return {"cancelled": len(rows), "source_id": str(source_id)}


@router.post("/{source_id}/retry", status_code=202)
async def retry_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Re-dispatch ingest_source for a cancelled or errored source.

    Tier 3 strict resume: relies on idempotent task entry + per-stage
    persistence to skip stages that already completed.
    """
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")

    # PRD §3 — stale sources are technically ``ready`` but the embed model
    # they were built against is no longer routed. Allow re-processing
    # those without needing the user to mark them as errored first.
    allow_retry = {"cancelled", "error", "pending"}
    if source.status == "ready":
        current_embed = await _current_embedding_model_name(db)
        stored_embed = None
        if isinstance(source.metadata_, dict):
            stored_embed = source.metadata_.get("embed_model") or source.metadata_.get(
                "embedding_model"
            )
        if stored_embed and current_embed and stored_embed != current_embed:
            allow_retry = allow_retry | {"ready"}
    if source.status not in allow_retry:
        raise HTTPException(
            409,
            f"Source is {source.status!r}; only stale / cancelled / error / pending sources can be retried",
        )

    # Revoke any in-flight celery task before re-dispatching. We do this for
    # ``error`` and ``cancelled`` too because Celery's ``acks_late`` +
    # visibility_timeout can redeliver a task we already gave up on (e.g.
    # the worker died mid-run and the broker still holds the unacked message).
    # If we skip the revoke, the redelivered run races our new task and both
    # finish concurrently — see the duplicate-course_generation bug.
    if source.status in {"pending", "error", "cancelled"} and source.celery_task_id:
        await abort_job(source.celery_task_id)

    # Reset cancel flag on the active SourceTask rows.
    rows = (
        await db.execute(
            select(SourceTask).where(SourceTask.source_id == source_id)
        )
    ).scalars().all()
    for row in rows:
        row.cancel_requested = False

    source.status = "pending"
    if isinstance(source.metadata_, dict):
        new_meta = dict(source.metadata_)
        new_meta.pop("error", None)
        source.metadata_ = new_meta

    job_id = await enqueue("ingest_source", str(source.id))
    source.celery_task_id = job_id
    await create_source_task(
        db,
        source_id=source.id,
        task_type="source_processing",
        status="pending",
        celery_task_id=job_id,
    )
    await db.commit()
    return {"task_id": job_id, "source_id": str(source_id)}


@router.delete("/{source_id}", status_code=202)
async def delete_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Soft-delete a source.

    Works in every non-deleted state: active sources have their Celery tasks
    revoked and ``cancel_requested`` set so any in-flight worker exits at the
    next safe break point. The source row stays in the database with
    ``status='deleted'`` and is filtered out of all default queries.
    """
    from datetime import datetime, timezone

    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")

    active_rows = (
        await db.execute(
            select(SourceTask).where(
                SourceTask.source_id == source_id,
                SourceTask.status.in_(("pending", "running")),
            )
        )
    ).scalars().all()
    for row in active_rows:
        row.cancel_requested = True
        if row.celery_task_id:
            await abort_job(row.celery_task_id)

    if source.celery_task_id:
        await abort_job(source.celery_task_id)

    source.status = "deleted"
    if isinstance(source.metadata_, dict):
        new_meta = dict(source.metadata_)
        new_meta["deleted_at"] = datetime.now(timezone.utc).isoformat()
        source.metadata_ = new_meta

    await db.commit()
    return {"deleted": True, "source_id": str(source_id)}


@router.post("/{source_id}/generate-course", status_code=202)
async def generate_course_for_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Dispatch async course generation for a ready source.

    The synchronous ``POST /courses/generate`` runs the full LLM pipeline in
    request scope (minutes long); calling it from the source drawer is
    unsuitable because the user can't see in-flight state and can re-fire it.
    This endpoint mirrors the auto-flow used at the end of content ingestion:
    create a ``pending`` ``course_generation`` SourceTask row, then dispatch
    ``generate_course_task`` with the pre-allocated task id. The list endpoint
    picks up the pending task immediately so the UI shows 课程生成中.
    """
    from uuid import uuid4

    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")

    if source.status != "ready":
        raise HTTPException(
            409,
            f"Source is {source.status!r}; only ready sources can generate a course",
        )

    existing_active = (
        await db.execute(
            select(SourceTask)
            .where(
                SourceTask.source_id == source_id,
                SourceTask.task_type == "course_generation",
                SourceTask.status.in_(("pending", "running")),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        return {
            "task_id": existing_active.celery_task_id,
            "source_id": str(source_id),
            "status": "already_dispatched",
        }

    existing_course = (
        await db.execute(
            select(CourseSource.course_id)
            .join(Course, Course.id == CourseSource.course_id)
            .where(
                CourseSource.source_id == source_id,
                Course.created_by == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_course is not None:
        raise HTTPException(
            409,
            f"Source already has a generated course ({existing_course}); use regenerate instead",
        )

    queued_task_id = str(uuid4())
    await create_source_task(
        db,
        source_id=source_id,
        task_type="course_generation",
        celery_task_id=queued_task_id,
        status="pending",
        stage="pending",
    )
    await db.commit()

    await dispatch_course_generation(
        payload={"source_id": str(source_id)},
        task_id=queued_task_id,
        user_id=str(user.id),
    )
    return {"task_id": queued_task_id, "source_id": str(source_id), "status": "dispatched"}


@router.get("/{source_id}/runs/{run_id}/events")
async def stream_run_events(
    source_id: uuid.UUID,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
):
    """Live AG-UI event stream for a course-generation run (replaces polling).

    The ARQ worker publishes the run's AG-UI events to a Redis stream; this
    endpoint subscribes and re-emits them as SSE. ``run_id`` is the course task
    id the dispatch endpoints return. Reconnecting replays from the start.
    """
    import redis.asyncio as aioredis

    from app.agentcore.events import RedisEventSink

    source = await db.get(Source, source_id)
    if not source or source.created_by != user.id:
        raise HTTPException(404, f"Source {source_id} not found")

    encoder = EventEncoder()
    redis = aioredis.from_url(get_settings().redis_url)

    async def event_stream():
        try:
            async for body in RedisEventSink.subscribe(redis, run_id):
                # body is the AG-UI event JSON; wrap in an SSE data frame.
                yield f"data: {body}\n\n"
        finally:
            await redis.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{source_id}/progress", response_model=SourceProgressResponse)
async def get_source_progress(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> SourceProgressResponse:
    """Aggregate progress for a source — DB-authoritative, no Celery state.

    Returns the latest SourceTask row per task_type so the frontend can render
    the full pipeline (source_processing + course_generation) in one read.
    """
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.created_by == user.id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")

    rows = (
        await db.execute(
            select(SourceTask)
            .where(SourceTask.source_id == source_id)
            .order_by(SourceTask.task_type, SourceTask.created_at.desc())
        )
    ).scalars().all()

    latest_by_type: dict[str, SourceTask] = {}
    for row in rows:
        latest_by_type.setdefault(row.task_type, row)

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
        for t in latest_by_type.values()
    ]

    course_id = next(
        (t.course_id for t in tasks if t.task_type == "course_generation" and t.course_id),
        None,
    )
    error = (source.metadata_ or {}).get("error") if isinstance(source.metadata_, dict) else None

    return SourceProgressResponse(
        source_id=source.id,
        source_status=source.status,
        error=error,
        course_id=course_id,
        tasks=tasks,
    )


@router.get("/{source_id}/chunks")
async def list_source_chunks(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """List the content chunks produced for a source (PRD §11 Phase E).

    Powers the Library detail drawer's Chunks tab — gives the user
    visibility into what the ingestion pipeline actually produced for
    this source, without exposing embeddings.
    """
    if not (await _user_owns_source(db, source_id, user.id)):
        raise HTTPException(404, f"Source {source_id} not found")

    total = (
        await db.execute(
            select(func.count())
            .select_from(ContentChunkModel)
            .where(ContentChunkModel.source_id == source_id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(ContentChunkModel)
            .where(ContentChunkModel.source_id == source_id)
            .order_by(ContentChunkModel.created_at)
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()
    items = [
        {
            "id": str(c.id),
            "text": c.text[:500] + ("…" if len(c.text) > 500 else ""),
            "length": len(c.text),
            "section_id": str(c.section_id) if c.section_id else None,
            "metadata": c.metadata_ or {},
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/{source_id}/citations")
async def list_source_citations(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """List every course generated from (or citing) this source.

    Powers the source-detail modal's "该资料生成的课程" section. For each
    course we return enough to render a version chip (``version_index``
    over the parent-chain root) and ordered sections.

    The order is newest-first so the row at the top is the one the
    Library row's Sparkle CTA would jump to (``latest_course_id``).
    """
    if not (await _user_owns_source(db, source_id, user.id)):
        raise HTTPException(404, f"Source {source_id} not found")

    # All courses generated from this source — covers original /
    # regenerate / multi-source synthesis (all three land a
    # course_sources row).
    course_rows = (
        await db.execute(
            select(Course)
            .join(CourseSource, CourseSource.course_id == Course.id)
            .where(
                CourseSource.source_id == source_id,
                Course.created_by == user.id,
            )
            .order_by(Course.created_at.desc())
        )
    ).scalars().all()
    if not course_rows:
        return {"items": [], "total": 0}

    course_ids = [c.id for c in course_rows]

    # Sections per course that explicitly point at this source — for
    # the "where exactly does this source appear" expansion inside each
    # course card.
    section_rows = (
        await db.execute(
            select(Section)
            .where(
                Section.course_id.in_(course_ids),
                Section.source_id == source_id,
            )
            .order_by(Section.course_id, Section.order_index)
        )
    ).scalars().all()
    sections_by_course: dict[uuid.UUID, list[dict]] = {}
    for s in section_rows:
        sections_by_course.setdefault(s.course_id, []).append(
            {
                "section_id": str(s.id),
                "title": s.title,
                "order_index": s.order_index,
            }
        )

    # Compute version_index per course over its parent chain. Cached so
    # sibling regenerations sharing the same root only pay one walk.
    from app.api.routes.courses import _compute_version_index

    version_cache: dict[uuid.UUID, int] = {}
    for c in course_rows:
        version_cache[c.id] = await _compute_version_index(db, c)

    items = []
    latest_id = course_rows[0].id  # already sorted desc by created_at
    for c in course_rows:
        items.append({
            "course_id": str(c.id),
            "course_title": c.title,
            "created_at": c.created_at.isoformat(),
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "regeneration_directive": c.regeneration_directive,
            "version_index": version_cache[c.id],
            "is_latest": c.id == latest_id,
            "sections": sections_by_course.get(c.id, []),
        })
    return {"items": items, "total": len(items)}


async def _user_owns_source(db: AsyncSession, source_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(Source.id).where(
                Source.id == source_id,
                Source.created_by == user_id,
                Source.status != "deleted",
            )
        )
    ).scalar_one_or_none() is not None


@router.get("/{source_id}/file")
async def get_source_file(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> FileResponse:
    """Serve an uploaded PDF file for the owning user."""
    result = await db.execute(
        select(Source).where(
            Source.id == source_id,
            Source.created_by == user.id,
            Source.status != "deleted",
        )
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
        id=task.id,
        task_type=task.task_type,
        status=task.status,
        stage=task.stage,
        error_summary=task.error_summary,
        celery_task_id=task.celery_task_id,
        metadata_=task.metadata_ or {},
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
            id=task.id,
            task_type=task.task_type,
            status=task.status,
            stage=task.stage,
            error_summary=task.error_summary,
            celery_task_id=task.celery_task_id,
            metadata_=task.metadata_ or {},
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
    duplicate_of_source_id: uuid.UUID | None = None,
    duplicate_reason: str | None = None,
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

    embed = await _build_source_embed(
        db,
        source=source,
        latest_processing_task=latest_processing_task,
    )

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
        duplicate_of_source_id=duplicate_of_source_id,
        duplicate_reason=duplicate_reason,
        embed=embed,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


_EMBEDDING_ROUTE_CACHE: dict[str, str | None] = {"name": None}


async def _current_embedding_model_name(db: AsyncSession) -> str | None:
    """Return the model_name currently routed for ``task_type='embedding'``."""
    from app.db.models.model_config import ModelRouteConfig

    if _EMBEDDING_ROUTE_CACHE.get("loaded"):
        return _EMBEDDING_ROUTE_CACHE.get("name")
    row = (
        await db.execute(
            select(ModelRouteConfig.model_name).where(
                ModelRouteConfig.task_type == "embedding"
            )
        )
    ).first()
    _EMBEDDING_ROUTE_CACHE["name"] = row[0] if row else None
    _EMBEDDING_ROUTE_CACHE["loaded"] = True
    return _EMBEDDING_ROUTE_CACHE["name"]


def invalidate_embedding_route_cache() -> None:
    """Call after the user changes the embedding route in Settings."""
    _EMBEDDING_ROUTE_CACHE.clear()


async def _build_source_embed(
    db: AsyncSession,
    *,
    source: Source,
    latest_processing_task: SourceTaskSummary | None,
) -> SourceEmbed:
    """Fold flat source/task fields into the PRD §9 embed sub-object.

    The 5-state taxonomy:

    - ``ready``   — pipeline finished and the stored embed model still
                    matches the currently-routed embedding model.
    - ``running`` — Source.status is one of the active in-flight values
                    OR the latest task row is running/progress.
    - ``queued``  — pending dispatch.
    - ``failed``  — Source.status == 'error' or latest task row failed.
    - ``stale``   — was ready, but the model has been switched since.
    """
    meta = source.metadata_ if isinstance(source.metadata_, dict) else {}
    used_model = meta.get("embed_model") or meta.get("embedding_model")
    chunks = meta.get("chunks") if isinstance(meta.get("chunks"), int) else None
    vectors = meta.get("vectors") if isinstance(meta.get("vectors"), int) else None
    err = meta.get("error") if isinstance(meta.get("error"), str) else None

    if source.status == "error":
        return SourceEmbed(status="failed", model=used_model, error=err)
    if source.status == "cancelled" or (
        latest_processing_task and latest_processing_task.status == "cancelled"
    ):
        return SourceEmbed(status="cancelled", model=used_model)
    if (
        latest_processing_task
        and latest_processing_task.status == "failure"
    ):
        return SourceEmbed(
            status="failed",
            model=used_model,
            error=latest_processing_task.error_summary or err,
        )
    if source.status in _ACTIVE_SOURCE_STATUSES or (
        latest_processing_task and latest_processing_task.status in {"running", "progress"}
    ):
        return SourceEmbed(status="running", model=used_model)
    if source.status == "pending" or (
        latest_processing_task and latest_processing_task.status == "pending"
    ):
        return SourceEmbed(status="queued", model=used_model)
    if source.status == "ready":
        current = await _current_embedding_model_name(db)
        if used_model and current and used_model != current:
            return SourceEmbed(
                status="stale",
                model=used_model,
                chunks=chunks,
                vectors=vectors,
                reason=f"embed model upgraded: {used_model} → {current}",
            )
        return SourceEmbed(
            status="ready",
            model=used_model,
            chunks=chunks,
            vectors=vectors,
        )
    return SourceEmbed(status="queued", model=used_model)


def _build_source_base_query(
    *,
    user_id: uuid.UUID,
    query: str | None,
    source_type: str | None,
):
    filters = [Source.created_by == user_id, Source.status != "deleted"]

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
    if source.status == "cancelled":
        return "failure"

    tasks = [task for task in (latest_processing_task, latest_course_task) if task]
    if any(task.status == "failure" for task in tasks):
        return "failure"
    if latest_processing_task and latest_processing_task.status == "cancelled":
        return "failure"

    if source.status in _ACTIVE_SOURCE_STATUSES or any(
        task.status in _ACTIVE_TASK_STATUSES for task in tasks
    ):
        return "processing"

    return "ready"
