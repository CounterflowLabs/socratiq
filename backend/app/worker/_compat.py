"""Compatibility shim so Celery-shaped async task bodies run unchanged on ARQ.

The intricate ``_*_async(task, ...)`` implementations used Celery's bound
``self`` for two things only: ``self.update_state(...)`` (progress, now tracked
via SourceTask rows) and ``self.request.id`` (the task id). This shim provides
both — ``update_state`` is a no-op, ``request.id`` is the ARQ job id — so the
task bodies don't need to be touched during the migration.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _NoopTask:
    def __init__(self, job_id: str | None = None) -> None:
        self.request = SimpleNamespace(id=job_id)

    def update_state(self, **kwargs: Any) -> None:  # noqa: D401, ARG002
        return None


def task_shim(ctx: dict) -> _NoopTask:
    """Build a Celery-``self``-shaped shim from the ARQ job context."""
    return _NoopTask(ctx.get("job_id"))
