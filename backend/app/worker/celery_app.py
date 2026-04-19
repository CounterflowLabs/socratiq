"""Celery application configuration."""

from celery import Celery

from app.config import get_settings

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

# Explicitly import tasks so they register with Celery
import app.worker.tasks.content_ingestion  # noqa: F401
import app.worker.tasks.course_generation  # noqa: F401
import app.worker.tasks.memory_pruning  # noqa: F401
