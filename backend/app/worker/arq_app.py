"""ARQ worker application (replaces Celery).

Run with::

    arq app.worker.arq_app.WorkerSettings

One shared ``WorkerResources`` (engine + ModelRouter) is created in
``on_startup`` and reused across jobs — safe because ARQ runs every job in a
single persistent event loop (unlike Celery's prefork-per-task model that
forced a fresh pool per task). Startup also runs the orphaned-task reapers.

Task functions are registered with explicit names so enqueue call sites use
stable strings (``enqueue("generate_course", ...)``). ``max_tries=1`` matches
the previous effective behavior (tasks failed without auto-retry).
"""

from __future__ import annotations

import logging

from arq import func

from app.worker.queue import get_redis_settings
from app.worker.resources import _create_worker_resources

logger = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    resources = _create_worker_resources()
    ctx["resources"] = resources
    from app.worker.reapers import run_startup_reapers

    try:
        await run_startup_reapers(resources)
    except Exception:  # noqa: BLE001
        logger.exception("Startup reapers failed")


async def on_shutdown(ctx: dict) -> None:
    resources = ctx.get("resources")
    if resources is not None:
        await resources.engine.dispose()


def _functions():
    # Imported lazily so importing this module (e.g. for WorkerSettings in the
    # API process to read redis settings) doesn't drag in the whole task graph.
    from app.worker.tasks.content_ingestion import clone_source, ingest_source
    from app.worker.tasks.course_generation import generate_course
    from app.worker.tasks.course_generation_multi import generate_multi
    from app.worker.tasks.course_regeneration import regenerate_course
    from app.worker.tasks.exercise_generation import generate_section_exercises
    from app.worker.tasks.lesson_regeneration import regenerate_section_lesson
    from app.worker.tasks.memory_pruning import prune_expired_memories
    from app.worker.tasks.sentence_course import generate_sentence_course

    long = 3600  # whisper transcription / multi-source generation can be slow
    return [
        func(ingest_source, name="ingest_source", max_tries=1, timeout=long),
        func(clone_source, name="clone_source", max_tries=1, timeout=300),
        func(generate_course, name="generate_course", max_tries=1, timeout=long),
        func(generate_multi, name="generate_multi", max_tries=1, timeout=long),
        func(generate_sentence_course, name="generate_sentence_course", max_tries=1, timeout=long),
        func(regenerate_course, name="regenerate_course", max_tries=1, timeout=long),
        func(generate_section_exercises, name="generate_section_exercises", max_tries=1, timeout=300),
        func(regenerate_section_lesson, name="regenerate_section_lesson", max_tries=1, timeout=300),
        func(prune_expired_memories, name="prune_expired_memories", max_tries=1, timeout=120),
    ]


class WorkerSettings:
    functions = _functions()
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = get_redis_settings()
    max_jobs = 4              # was celery --concurrency=4
    allow_abort_jobs = True   # enables Job.abort() (revoke replacement)
    job_timeout = 3600
