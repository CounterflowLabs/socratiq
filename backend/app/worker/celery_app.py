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
    # PRD §11 Phase B: physically separate ingestion and generation so a
    # stuck embedding cannot starve generation (or vice versa). The two
    # workloads share the same Ollama process when running locally, but
    # at the queue level they're independent — one queue can be paused,
    # drained, or scaled separately.
    task_default_queue="generate_queue",
    task_routes={
        # Embedding pipeline — adds new material to the library.
        "content_ingestion.ingest_source": {"queue": "embed_queue"},
        "content_ingestion.clone_source": {"queue": "embed_queue"},
        # Generation pipeline — consumes embedded sources.
        "course_generation.generate_course": {"queue": "generate_queue"},
        "course_generation.generate_multi": {"queue": "generate_queue"},
        "course_regeneration.regenerate_course": {"queue": "generate_queue"},
        "lesson_regeneration.regenerate_for_section": {"queue": "generate_queue"},
        "exercise_generation.generate_for_section": {"queue": "generate_queue"},
        # Housekeeping stays on the default queue.
    },
)


# Explicitly import tasks so they register with Celery
import app.worker.tasks.content_ingestion  # noqa: F401, E402
import app.worker.tasks.course_generation  # noqa: F401, E402
import app.worker.tasks.course_generation_multi  # noqa: F401, E402
import app.worker.tasks.course_regeneration  # noqa: F401, E402
import app.worker.tasks.exercise_generation  # noqa: F401, E402
import app.worker.tasks.lesson_regeneration  # noqa: F401, E402
import app.worker.tasks.memory_pruning  # noqa: F401, E402

# Reaper signal handlers (worker_ready)
import app.worker.reapers  # noqa: F401, E402
