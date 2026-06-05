"""Reapers: recover tasks orphaned across worker restarts.

Two reapers run on ``worker_ready``:

1. **course_generation** — when ``finish_source_processing_and_enqueue_course``
   writes a SourceTask row with ``status='pending'`` and a pre-allocated
   ``celery_task_id``, the actual ``apply_async`` happens *after* the DB
   commit. If the worker crashes between those two steps, the task row stays
   pending forever — Celery never accepted it, and AsyncResult would just say
   ``PENDING`` for the rest of time. This reaper re-dispatches them.

2. **source_processing** — content ingestion has no commit-then-dispatch
   race, but if a worker dies mid-pipeline (extract / analyze / store /
   embed), the Source row stays in an intermediate ``processing`` status and
   the SourceTask row stays ``running``. We mark these as ``error`` and let
   the user retry from the UI — auto-redispatch is risky because the failure
   may have been caused by a bug we'd just hit again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.models.source import Source
from app.db.models.source_task import SourceTask

logger = logging.getLogger(__name__)

_REAPER_GRACE = timedelta(minutes=2)

_SOURCE_PROCESSING_ACTIVE_STATUSES = (
    "pending",
    "processing",
    "extracting",
    "analyzing",
    "generating_lessons",
    "generating_labs",
    "storing",
    "embedding",
)

_STARTUP_INTERRUPT_MESSAGE = "服务重启中断，请重试"


async def _reap_pending_course_tasks(resources) -> int:
    """Re-dispatch pending course_generation tasks older than the grace window."""
    from app.services.source_tasks import dispatch_course_generation

    # source_tasks.created_at is TIMESTAMP WITHOUT TIME ZONE; compare with naive UTC.
    cutoff = datetime.utcnow() - _REAPER_GRACE
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
                await dispatch_course_generation(
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


async def _reap_stuck_source_processing(resources) -> int:
    """Mark source-processing tasks orphaned by a worker crash as failed.

    On worker boot, any SourceTask still in ``running`` is by definition stale
    — the previous worker died holding it. ``pending`` rows older than the
    grace window were never picked up. In both cases we flip the SourceTask
    to ``failure`` and the parent Source to ``error`` with a clear message so
    the UI surfaces a retry button.
    """
    cutoff = datetime.utcnow() - _REAPER_GRACE
    repaired = 0

    if resources is not None:
        async with resources.session_factory() as db:
            rows = (
                await db.execute(
                    select(SourceTask)
                    .where(
                        SourceTask.task_type == "source_processing",
                        SourceTask.status.in_(("pending", "running")),
                    )
                )
            ).scalars().all()

            for task in rows:
                # Skip very-fresh pending rows: they might still be on the
                # broker queue and a worker could legitimately pick them up.
                if task.status == "pending" and task.created_at and task.created_at > cutoff:
                    continue

                task.status = "failure"
                task.error_summary = _STARTUP_INTERRUPT_MESSAGE

                source = await db.get(Source, task.source_id)
                if source and source.status in _SOURCE_PROCESSING_ACTIVE_STATUSES:
                    source.status = "error"
                    if isinstance(source.metadata_, dict):
                        source.metadata_ = {
                            **source.metadata_,
                            "error": _STARTUP_INTERRUPT_MESSAGE,
                        }
                repaired += 1
                logger.info(
                    "Reaper marked source_processing task %s (source %s) as failed after restart",
                    task.celery_task_id or task.id,
                    task.source_id,
                )

            if repaired:
                await db.commit()

    return repaired


async def run_startup_reapers(resources) -> None:
    """Run both reapers once at ARQ worker startup (was Celery worker_ready).

    Uses the worker's shared resources; never raises (each reaper is isolated)
    so a reaper failure can't prevent the worker from coming up.
    """
    try:
        count = await _reap_pending_course_tasks(resources)
        if count:
            logger.info("Reaper re-dispatched %d pending course tasks at startup", count)
    except Exception:
        logger.exception("Course-generation reaper failed at startup")

    try:
        count = await _reap_stuck_source_processing(resources)
        if count:
            logger.info(
                "Reaper marked %d stuck source_processing tasks as failed at startup",
                count,
            )
    except Exception:
        logger.exception("Source-processing reaper failed at startup")
