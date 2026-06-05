"""ARQ task queue — enqueue / abort / status helpers.

Replaces the Celery transport. One lazily-created ``ArqRedis`` pool per process
(the API process enqueues; the worker process consumes). Centralizing the
queue API here keeps call sites (routes, dispatch helpers) decoupled from ARQ
specifics and from the Celery semantics they replaced:

  * ``enqueue(name, *args, job_id=...)`` ← Celery ``.delay()`` / ``.apply_async``
    A pre-chosen ``job_id`` gives idempotent enqueue (ARQ dedups by job id),
    matching the old pre-allocated ``celery_task_id`` pattern.
  * ``abort_job(job_id)``                ← ``AsyncResult(id).revoke()``
  * ``get_job_state(job_id)``            ← ``AsyncResult(id).state``
"""

from __future__ import annotations

import logging

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def get_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(get_redis_settings())
    return _pool


async def enqueue(name: str, *args, job_id: str | None = None, **kwargs) -> str | None:
    """Enqueue a job. Returns the job id, or None if a job with ``job_id``
    already exists (ARQ dedup — the idempotency guarantee the old pre-allocated
    ``celery_task_id`` relied on)."""
    pool = await get_pool()
    job = await pool.enqueue_job(name, *args, _job_id=job_id, **kwargs)
    return job.job_id if job is not None else None


async def abort_job(job_id: str | None) -> bool:
    """Request cancellation of a queued/running job (needs allow_abort_jobs)."""
    if not job_id:
        return False
    pool = await get_pool()
    try:
        return await Job(job_id, pool).abort(timeout=0)
    except Exception:  # noqa: BLE001
        logger.warning("arq abort failed for job %s", job_id, exc_info=True)
        return False


_STATUS_MAP = {
    JobStatus.deferred: "pending",
    JobStatus.queued: "pending",
    JobStatus.in_progress: "running",
    JobStatus.complete: "success",
    JobStatus.not_found: "unknown",
}


async def get_job_state(job_id: str | None) -> str:
    """Coarse job state for the status endpoints (pending/running/success/unknown).

    Note: the authoritative ingest/generation progress lives in the
    ``SourceTask`` rows; this is only the transport-level view.
    """
    if not job_id:
        return "unknown"
    pool = await get_pool()
    status = await Job(job_id, pool).status()
    return _STATUS_MAP.get(status, "unknown")
