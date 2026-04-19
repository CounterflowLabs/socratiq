"""Redis subscriber that listens for source completion events and triggers clone tasks."""

import json
import logging
import threading

import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)


def start_ref_subscriber() -> None:
    """Start the Redis subscriber in a daemon thread. Call from worker_ready signal."""
    thread = threading.Thread(target=_run_subscriber, daemon=True, name="ref-subscriber")
    thread.start()
    logger.info("Started ref_source subscriber thread")


def _run_subscriber() -> None:
    """Subscribe to source:done:* and handle events."""
    import asyncio

    settings = get_settings()
    r = redis.Redis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    pubsub.psubscribe("source:done:*")

    logger.info("Ref subscriber listening on source:done:*")
    for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        try:
            payload = json.loads(message["data"])
            source_id = payload["source_id"]
            status = payload["status"]
            logger.info(f"Ref subscriber received: source={source_id} status={status}")
            asyncio.run(_handle_source_done(source_id, status))
        except Exception as e:
            logger.error(f"Ref subscriber error handling message: {e}", exc_info=True)


async def _handle_source_done(ref_source_id: str, status: str) -> None:
    """Find waiting sources and dispatch clone or mark error."""
    from uuid import UUID
    from app.db.models.source import Source

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=5)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            ref_sid = UUID(ref_source_id)
            result = await db.execute(
                select(Source).where(
                    Source.ref_source_id == ref_sid,
                    Source.status == "waiting_donor",
                )
            )
            waiters = result.scalars().all()

            if not waiters:
                return

            logger.info(f"Found {len(waiters)} waiting sources for ref {ref_source_id}")

            if status == "ready":
                from app.worker.tasks.content_ingestion import clone_source
                for waiter in waiters:
                    result = clone_source.delay(str(waiter.id), ref_source_id)
                    waiter.celery_task_id = result.id
                    waiter.status = "pending"
                    logger.info(f"Dispatched clone_source for {waiter.id}")
            else:
                for waiter in waiters:
                    waiter.status = "error"
                    waiter.metadata_ = {**waiter.metadata_, "error": "引用源处理失败"}
                    logger.info(f"Marked waiter {waiter.id} as error (ref failed)")

            await db.commit()
    finally:
        await engine.dispose()
