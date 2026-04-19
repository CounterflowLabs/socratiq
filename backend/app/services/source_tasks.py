"""Helpers for persisted source task orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source import Source
from app.db.models.source_task import SourceTask


class _GenerateCourseTaskProxy:
    """Lazy proxy to avoid circular imports between workers and task helpers."""

    def apply_async(self, *args, **kwargs):
        from app.worker.tasks.course_generation import generate_course_task as task

        return task.apply_async(*args, **kwargs)


generate_course_task = _GenerateCourseTaskProxy()


@dataclass(frozen=True)
class PreparedCourseGeneration:
    """Post-commit dispatch details for a preallocated course task."""

    payload: dict[str, Any]
    task_id: str
    fallback_task_id: str | None
    user_id: str | None


@dataclass(frozen=True)
class SourceProcessingCompletion:
    """Persisted completion data for a source-processing run."""

    result: dict[str, Any]
    course_dispatch: PreparedCourseGeneration


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
) -> SourceProcessingCompletion:
    """Mark source processing ready and enqueue a persisted course task."""
    queued_task_id = str(uuid4())
    previous_task_id = (
        processing_task.celery_task_id
        if processing_task is not None
        else source.celery_task_id
    )
    source.status = "ready"
    source.celery_task_id = queued_task_id

    await mark_source_task(
        db,
        source_id=source.id,
        task_type="source_processing",
        status="success",
        stage="ready",
        error_summary=None,
        celery_task_id=(
            processing_task.celery_task_id if processing_task is not None else None
        ),
    )

    metadata = source.metadata_ or {}
    await create_source_task(
        db,
        source_id=source.id,
        task_type="course_generation",
        celery_task_id=queued_task_id,
        status="pending",
        stage="pending",
    )
    await db.flush()

    return SourceProcessingCompletion(
        result={
            **payload,
            "status": "ready",
            "queued_course_task_id": queued_task_id,
        },
        course_dispatch=PreparedCourseGeneration(
            payload=payload,
            task_id=queued_task_id,
            fallback_task_id=previous_task_id,
            user_id=metadata.get("pending_user_id") or str(source.created_by),
        ),
    )


def dispatch_course_generation(
    *,
    payload: dict[str, Any],
    task_id: str,
    user_id: str | None,
):
    """Dispatch the already-persisted course-generation task."""
    return generate_course_task.apply_async(
        args=[payload],
        kwargs={"user_id": user_id},
        task_id=task_id,
    )


async def recover_course_generation_dispatch_failure(
    *,
    session_factory,
    source_id,
    course_task_id: str,
    fallback_task_id: str | None,
    error_message: str,
) -> None:
    """Rollback source task pointers after post-commit dispatch failure."""
    session_or_cm = session_factory()

    if hasattr(session_or_cm, "__aenter__"):
        async with session_or_cm as db:
            await _recover_course_generation_dispatch_failure_in_session(
                db=db,
                source_id=source_id,
                course_task_id=course_task_id,
                fallback_task_id=fallback_task_id,
                error_message=error_message,
            )
            await db.commit()
        return

    db = session_or_cm
    await _recover_course_generation_dispatch_failure_in_session(
        db=db,
        source_id=source_id,
        course_task_id=course_task_id,
        fallback_task_id=fallback_task_id,
        error_message=error_message,
    )
    await db.commit()


async def _recover_course_generation_dispatch_failure_in_session(
    *,
    db: AsyncSession,
    source_id,
    course_task_id: str,
    fallback_task_id: str | None,
    error_message: str,
) -> None:
    """Apply dispatch recovery changes inside an existing session."""
    source = await db.get(Source, source_id)
    if source is not None:
        source.status = "ready"
        source.celery_task_id = fallback_task_id

    result = await db.execute(
        select(SourceTask)
        .where(
            SourceTask.source_id == source_id,
            SourceTask.task_type == "course_generation",
            SourceTask.celery_task_id == course_task_id,
        )
        .order_by(SourceTask.created_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if task is not None:
        task.status = "failure"
        task.stage = "error"
        task.error_summary = error_message

    await db.flush()
