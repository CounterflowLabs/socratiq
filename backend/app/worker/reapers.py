"""Reaper: re-dispatch course-generation tasks orphaned by commit-then-dispatch races.

When ``finish_source_processing_and_enqueue_course`` writes a SourceTask row
with ``status='pending'`` and a pre-allocated ``celery_task_id``, the actual
``apply_async`` happens *after* the DB commit. If the worker crashes between
those two steps, the task row stays pending forever — Celery never accepted
it, and AsyncResult would just say ``PENDING`` for the rest of time.

This reaper scans for ``course_generation`` tasks that have been pending
beyond a grace window and re-dispatches them with the same task_id. The
``generate_course_task`` worker is now idempotent at entry, so a re-dispatch
that races with the original (if it existed) is safe.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery.signals import worker_ready
from sqlalchemy import select

from app.db.models.source_task import SourceTask
from app.worker.resources import get_worker_resources

logger = logging.getLogger(__name__)

_REAPER_GRACE = timedelta(minutes=2)


async def _reap_pending_course_tasks() -> int:
    """Re-dispatch pending course_generation tasks older than the grace window."""
    from app.services.source_tasks import dispatch_course_generation

    resources = get_worker_resources()
    cutoff = datetime.now(timezone.utc) - _REAPER_GRACE
    redispatched = 0

    async with resources.session_factory() as db:
        rows = (
            await db.execute(
                select(SourceTask)
                .where(
                    SourceTask.task_type == "course_generation",
                    SourceTask.status == "pending",
                    SourceTask.created_at < cutoff,
                )
            )
        ).scalars().all()

        for task in rows:
            if not task.celery_task_id:
                continue
            payload = {"source_id": str(task.source_id)}
            user_id = (
                task.metadata_.get("pending_user_id")
                if isinstance(task.metadata_, dict)
                else None
            )
            try:
                dispatch_course_generation(
                    payload=payload,
                    task_id=task.celery_task_id,
                    user_id=user_id,
                )
                redispatched += 1
                logger.info(
                    "Reaper re-dispatched course_generation task %s (source %s)",
                    task.celery_task_id,
                    task.source_id,
                )
            except Exception:
                logger.exception(
                    "Reaper failed to re-dispatch task %s",
                    task.celery_task_id,
                )

    return redispatched


@worker_ready.connect
def _on_worker_ready(**_kwargs) -> None:
    """Run once when the worker boots — clears any pending backlog."""
    try:
        count = asyncio.run(_reap_pending_course_tasks())
        if count:
            logger.info("Reaper re-dispatched %d pending tasks at startup", count)
    except Exception:
        logger.exception("Reaper failed during worker_ready")
