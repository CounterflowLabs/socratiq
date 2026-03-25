"""Celery task for pruning expired episodic memories."""

import logging

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="memory.prune_expired")
def prune_expired_memories():
    """Delete episodic memories past their expiry date.

    Low-importance memories are created with an ``expires_at`` timestamp.
    This task should be scheduled periodically (e.g. daily via Celery Beat)
    to clean them up.
    """
    import asyncio

    return asyncio.run(_prune_async())


async def _prune_async() -> dict:
    from datetime import datetime

    from sqlalchemy import delete

    from app.db.database import async_session_factory
    from app.db.models.episodic_memory import EpisodicMemory

    async with async_session_factory() as db:
        result = await db.execute(
            delete(EpisodicMemory).where(
                EpisodicMemory.expires_at.isnot(None),
                EpisodicMemory.expires_at <= datetime.utcnow(),  # noqa: DTZ003
            )
        )
        await db.commit()
        count = result.rowcount
        logger.info("Pruned %d expired episodic memories", count)
        return {"pruned": count}
