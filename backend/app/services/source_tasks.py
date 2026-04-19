"""Helpers for persisted source task orchestration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source import Source
from app.db.models.source_task import SourceTask


class _GenerateCourseTaskProxy:
    """Lazy proxy to avoid circular imports between workers and task helpers."""

    def delay(self, *args, **kwargs):
        from app.worker.tasks.course_generation import generate_course_task as task

        return task.delay(*args, **kwargs)


generate_course_task = _GenerateCourseTaskProxy()


async def create_source_task(
    db: AsyncSession,
    *,
    source_id,
    task_type: str,
    celery_task_id: str | None = None,
    status: str = "pending",
    stage: str | None = None,
    error_summary: str | None = None,
    metadata_: dict[str, Any] | None = None,
) -> SourceTask:
    """Create and flush a persisted task row for a source."""
    task = SourceTask(
        source_id=source_id,
        task_type=task_type,
        status=status,
        stage=stage,
        error_summary=error_summary,
        celery_task_id=celery_task_id,
        metadata_=metadata_ or {},
    )
    db.add(task)
    await db.flush()
    return task


async def mark_source_task(
    db: AsyncSession,
    *,
    source_id,
    task_type: str,
    status: str,
    stage: str | None = None,
    error_summary: str | None = None,
    celery_task_id: str | None = None,
    metadata_: dict[str, Any] | None = None,
) -> SourceTask | None:
    """Update the latest persisted task row for a source/task type."""
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
        if celery_task_id is None and status == "pending":
            return await create_source_task(
                db,
                source_id=source_id,
                task_type=task_type,
                status=status,
                stage=stage,
                error_summary=error_summary,
                metadata_=metadata_,
            )
        task = await create_source_task(
            db,
            source_id=source_id,
            task_type=task_type,
            celery_task_id=celery_task_id,
            status=status,
            stage=stage,
            error_summary=error_summary,
            metadata_=metadata_,
        )
        return task

    task.status = status
    if stage is not None:
        task.stage = stage
    if error_summary is not None or status != "failure":
        task.error_summary = error_summary
    if celery_task_id is not None:
        task.celery_task_id = celery_task_id
    if metadata_ is not None:
        task.metadata_ = {**(task.metadata_ or {}), **metadata_}

    await db.flush()
    return task


async def finish_source_processing_and_enqueue_course(
    db: AsyncSession,
    *,
    source: Source,
    processing_task: SourceTask | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Mark source processing ready and enqueue a persisted course task."""
    source.status = "ready"

    if processing_task is not None:
        processing_task.status = "success"
        processing_task.stage = "ready"
        processing_task.error_summary = None

    metadata = source.metadata_ or {}
    queued_task = generate_course_task.delay(
        payload,
        goal=metadata.get("pending_goal"),
        user_id=metadata.get("pending_user_id") or str(source.created_by),
    )
    await create_source_task(
        db,
        source_id=source.id,
        task_type="course_generation",
        celery_task_id=queued_task.id,
        status="pending",
        stage="pending",
    )
    await db.flush()

    return {
        **payload,
        "status": "ready",
        "queued_course_task_id": queued_task.id,
    }
