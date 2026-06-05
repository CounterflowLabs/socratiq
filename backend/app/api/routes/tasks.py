"""API routes for the unified tasks queue.

Surfaces the rows from ``source_tasks`` folded into the two-type taxonomy
the UI knows about (``embed`` vs ``generate``) — see PRD §3.

Legacy ``GET /tasks/{id}/status`` is still served here for back-compat
(it reads the Celery result backend) but is marked deprecated.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_db, get_local_user
from app.db.models.course import Course
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.db.models.user import User
from app.models.task import (
    TaskListItem,
    TaskListResponse,
    map_task_status,
    map_task_type,
)
from app.worker.queue import abort_job, enqueue, get_job_state

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

_UI_TYPE_TO_RAW = {
    "embed": ("source_processing",),
    "generate": ("course_generation", "course_regeneration"),
}
_UI_STATUS_TO_RAW = {
    "running": ("running", "progress"),
    "queued": ("pending",),
    "done": ("success",),
    "failed": ("failure",),
}


def _filter_user(stmt: Select, user: User) -> Select:
    """Restrict tasks to those whose owning source belongs to the user."""
    return stmt.join(Source, Source.id == SourceTask.source_id).where(
        Source.created_by == user.id
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    type: Literal["all", "embed", "generate"] = "all",
    status: Literal["all", "running", "queued", "done", "failed"] = "all",
    skip: int = 0,
    limit: int = 50,
) -> TaskListResponse:
    """Unified, filterable task queue. Powers the ``/tasks`` screen."""

    # Aggregate counts first, before applying type/status filters, so the
    # filter chips always show totals across the user's tasks.
    base = _filter_user(
        select(SourceTask.task_type, SourceTask.status, func.count()).group_by(
            SourceTask.task_type, SourceTask.status
        ),
        user,
    )
    counts_by_type: dict[str, int] = {"all": 0, "embed": 0, "generate": 0}
    counts_by_status: dict[str, int] = {
        "all": 0,
        "running": 0,
        "queued": 0,
        "done": 0,
        "failed": 0,
    }
    for row in (await db.execute(base)).all():
        raw_type, raw_status, n = row
        ui_type = map_task_type(raw_type)
        if ui_type is None:
            continue
        ui_status = map_task_status(raw_status)
        counts_by_type["all"] += n
        counts_by_type[ui_type] += n
        counts_by_status["all"] += n
        counts_by_status[ui_status] += n

    # Page of tasks with source + course context joined in.
    course_alias = aliased(Course)
    items_stmt = (
        select(
            SourceTask,
            Source.title,
            Source.type,
            course_alias.id,
            course_alias.title,
        )
        .join(Source, Source.id == SourceTask.source_id)
        .outerjoin(
            course_alias,
            course_alias.id == func.cast(
                SourceTask.metadata_["course_id"].astext, type_=course_alias.id.type
            ),
        )
        .where(Source.created_by == user.id)
    )

    if type != "all":
        items_stmt = items_stmt.where(
            SourceTask.task_type.in_(_UI_TYPE_TO_RAW[type])
        )
    else:
        # Only surface task types we know how to display.
        items_stmt = items_stmt.where(
            SourceTask.task_type.in_(
                tuple(t for opts in _UI_TYPE_TO_RAW.values() for t in opts)
            )
        )
    if status != "all":
        items_stmt = items_stmt.where(
            SourceTask.status.in_(_UI_STATUS_TO_RAW[status])
        )

    total_stmt = select(func.count()).select_from(items_stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    page_rows = (
        await db.execute(
            items_stmt.order_by(SourceTask.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
    ).all()

    # ETA: estimate remaining time from the median duration of recent
    # successful tasks of the same type. Cheap one-shot query — capped by
    # the page size, so it never explodes when the queue is huge.
    eta_for_type = await _eta_seconds_by_type(db)

    items: list[TaskListItem] = []
    for task, source_title, source_type, course_id, course_title in page_rows:
        ui_type = map_task_type(task.task_type)
        if ui_type is None:
            continue
        eta_seconds = None
        if task.status in {"running", "progress", "pending"}:
            full = eta_for_type.get(task.task_type)
            if full is not None:
                # Subtract however long the task has already been running.
                from datetime import datetime, timezone

                running_for = (
                    datetime.now(timezone.utc)
                    - task.created_at.replace(tzinfo=timezone.utc)
                ).total_seconds()
                eta_seconds = max(0, int(full - running_for))
        items.append(
            TaskListItem(
                id=task.id,
                type=ui_type,
                raw_task_type=task.task_type,
                status=map_task_status(task.status),
                stage=task.stage,
                error=task.error_summary,
                eta_seconds=eta_seconds,
                started_at=task.created_at,
                updated_at=task.updated_at,
                finished_at=task.updated_at if task.status in {"success", "failure"} else None,
                source_id=task.source_id,
                source_title=source_title,
                source_type=source_type,
                course_id=course_id,
                course_title=course_title,
                celery_task_id=task.celery_task_id,
                cancel_requested=task.cancel_requested,
            )
        )

    return TaskListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        counts_by_type=counts_by_type,
        counts_by_status=counts_by_status,
    )


@router.post("/{task_id}/cancel", status_code=202)
async def cancel_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Cooperative cancel for a single task (PRD §5.5 row action).

    Looks the task up either by ``source_tasks.id`` *or*
    ``celery_task_id`` — the unified queue returns the former while
    legacy callers may pass the latter.
    """
    task = await _find_task_for_user(db, user, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")

    if task.status not in {"pending", "running", "progress"}:
        return {"task_id": str(task.id), "cancelled": False, "reason": "not_active"}

    task.cancel_requested = True
    if task.celery_task_id:
        await abort_job(task.celery_task_id)
    await db.commit()
    return {"task_id": str(task.id), "cancelled": True}


@router.post("/{task_id}/retry", status_code=202)
async def retry_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Re-dispatch a failed task (PRD §5.5 failed-state row action).

    For ``source_processing`` we re-run ingestion via the source-level
    retry. For ``course_generation`` we re-fire the same Celery task with
    the original metadata payload (multi-source aware).
    """
    from uuid import uuid4

    from app.db.models.source_task import SourceTask
    from app.services.source_tasks import create_source_task, dispatch_course_generation

    task = await _find_task_for_user(db, user, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    if task.status != "failure":
        raise HTTPException(
            409,
            f"Task is {task.status!r}; only failed tasks can be retried",
        )

    new_task_id = str(uuid4())

    if task.task_type == "source_processing":
        source = await db.get(Source, task.source_id)
        if source is None:
            raise HTTPException(404, f"Owning source {task.source_id} not found")
        source.status = "pending"
        if isinstance(source.metadata_, dict):
            new_meta = dict(source.metadata_)
            new_meta.pop("error", None)
            source.metadata_ = new_meta
        await enqueue("ingest_source", str(source.id), job_id=new_task_id)
        await create_source_task(
            db,
            source_id=source.id,
            task_type="source_processing",
            celery_task_id=new_task_id,
            status="pending",
        )
        await db.commit()
        return {"task_id": new_task_id, "status": "dispatched"}

    if task.task_type == "course_generation":
        meta = task.metadata_ or {}
        source_ids = meta.get("source_ids") or [str(task.source_id)]
        config = meta.get("config") or {}
        anchor = uuid.UUID(meta.get("anchor_source_id") or source_ids[0])
        for sid in source_ids:
            await create_source_task(
                db,
                source_id=uuid.UUID(sid),
                task_type="course_generation",
                celery_task_id=new_task_id if uuid.UUID(sid) == anchor else None,
                status="pending",
                stage="pending",
                metadata_={**meta, "retry_of": str(task.id)},
            )
        await db.commit()
        if len(source_ids) == 1 and not config:
            # Legacy single-source row pattern — keep using the simple wrapper
            await dispatch_course_generation(
                payload={"source_id": source_ids[0]},
                task_id=new_task_id,
                user_id=str(user.id),
            )
        else:
            await enqueue(
                "generate_multi",
                {
                    "source_ids": source_ids,
                    "title": meta.get("title"),
                    "config": config,
                },
                user_id=str(user.id),
                job_id=new_task_id,
            )
        return {"task_id": new_task_id, "status": "dispatched"}

    raise HTTPException(400, f"Task type {task.task_type!r} cannot be retried")


async def _eta_seconds_by_type(db: AsyncSession) -> dict[str, float]:
    """Median wall-clock for recent successful runs per task_type.

    Cheap heuristic — sampled from the last 200 success rows so the page
    cost stays flat. Returns ``{task_type: median_seconds}``.
    """
    from sqlalchemy import desc

    rows = (
        await db.execute(
            select(SourceTask.task_type, SourceTask.created_at, SourceTask.updated_at)
            .where(SourceTask.status == "success")
            .order_by(desc(SourceTask.updated_at))
            .limit(200)
        )
    ).all()
    by_type: dict[str, list[float]] = {}
    for task_type, created, updated in rows:
        secs = (updated - created).total_seconds()
        if secs <= 0:
            continue
        by_type.setdefault(task_type, []).append(secs)
    return {
        t: sorted(s)[len(s) // 2]
        for t, s in by_type.items()
        if s
    }


async def _find_task_for_user(
    db: AsyncSession, user: User, task_id: str
):
    """Find a SourceTask owned by the user, by either row id or celery id."""
    import uuid as _uuid
    from app.db.models.source_task import SourceTask

    candidates: list = []
    try:
        candidates.append(SourceTask.id == _uuid.UUID(task_id))
    except ValueError:
        pass
    candidates.append(SourceTask.celery_task_id == task_id)

    stmt = (
        select(SourceTask)
        .join(Source, Source.id == SourceTask.source_id)
        .where(or_(*candidates), Source.created_by == user.id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("/{task_id}/status", deprecated=True)
async def get_task_status(task_id: str, response: Response) -> dict:
    """Deprecated. Use ``GET /sources/{source_id}/progress`` instead.

    Reads from Celery's result backend (Redis), which has a TTL — once the
    result expires, ``state == "PENDING"`` is indistinguishable from "never
    queued". The DB-backed source progress endpoint is authoritative.
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 09 Jun 2026 00:00:00 GMT"
    response.headers["Link"] = (
        '</api/v1/sources/{source_id}/progress>; rel="successor-version"'
    )

    # Transport-level job state only (pending/running/success/unknown). The
    # authoritative result/progress lives in the SourceTask rows surfaced by
    # GET /sources/{source_id}/progress.
    return {"task_id": task_id, "state": await get_job_state(task_id)}
