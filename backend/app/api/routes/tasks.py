"""API routes for the unified tasks queue.

Surfaces the rows from ``source_tasks`` folded into the two-type taxonomy
the UI knows about (``embed`` vs ``generate``) — see PRD §3.

Legacy ``GET /tasks/{id}/status`` is still served here for back-compat
(it reads the Celery result backend) but is marked deprecated.
"""

from __future__ import annotations

from typing import Annotated, Literal

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, Response
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
from app.worker.celery_app import celery_app

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

    items: list[TaskListItem] = []
    for task, source_title, source_type, course_id, course_title in page_rows:
        ui_type = map_task_type(task.task_type)
        if ui_type is None:
            continue
        items.append(
            TaskListItem(
                id=task.id,
                type=ui_type,
                raw_task_type=task.task_type,
                status=map_task_status(task.status),
                stage=task.stage,
                error=task.error_summary,
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

    result = AsyncResult(task_id, app=celery_app)

    payload = {
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "SUCCESS":
        payload["result"] = result.result
    elif result.state == "FAILURE":
        payload["error"] = str(result.result)
    elif result.state == "PROGRESS" and result.info:
        payload["progress"] = result.info

    return payload
