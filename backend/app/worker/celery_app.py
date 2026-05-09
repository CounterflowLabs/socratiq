"""Celery application configuration."""

import asyncio
import logging

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.config import get_settings
from app.worker.resources import dispose_worker_resources, init_worker_resources

logger = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery(
    "socratiq",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@worker_process_init.connect
def _init_resources(**_kwargs) -> None:
    init_worker_resources()


@worker_process_shutdown.connect
def _dispose_resources(**_kwargs) -> None:
    try:
        asyncio.run(dispose_worker_resources())
    except RuntimeError:
        # If a loop is already running (rare during shutdown), skip dispose.
        logger.warning("Skipping worker resource dispose (event loop unavailable)")


# Explicitly import tasks so they register with Celery
import app.worker.tasks.content_ingestion  # noqa: F401, E402
import app.worker.tasks.course_generation  # noqa: F401, E402
import app.worker.tasks.course_regeneration  # noqa: F401, E402
import app.worker.tasks.memory_pruning  # noqa: F401, E402

# Reaper signal handlers (worker_ready)
import app.worker.reapers  # noqa: F401, E402
