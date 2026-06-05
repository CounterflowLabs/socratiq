"""ARQ task for pruning expired episodic memories."""

import logging

logger = logging.getLogger(__name__)


async def prune_expired_memories(ctx: dict) -> dict:
    """Delete episodic memories past their expiry date.

    Low-importance memories carry an ``expires_at`` timestamp. Schedule this
    periodically (e.g. via an ARQ cron job) to clean them up.
    """
    return await _prune_async()


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
