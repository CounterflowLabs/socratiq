"""Pydantic schemas for the unified Tasks queue.

Per PRD §3 the user-facing task surface has two types:

- ``embed`` — data ingestion (``source_tasks.task_type = source_processing``)
- ``generate`` — course generation/regeneration (``course_generation`` or
  ``course_regeneration``)

Backend keeps the granular task_type column; this schema folds it into the
two-type taxonomy the UI knows about.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TaskTypeUi = Literal["embed", "generate"]
TaskStatusUi = Literal["running", "queued", "done", "failed"]


class TaskListItem(BaseModel):
    """One row in the unified tasks queue."""

    id: uuid.UUID
    type: TaskTypeUi
    raw_task_type: str  # e.g. "source_processing" / "course_generation"
    status: TaskStatusUi
    stage: str | None = None
    error: str | None = None
    eta_seconds: int | None = None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None

    # Subject of the task — the source that's being embedded, or the source
    # the generation run is based on (we only point at one source for now;
    # multi-source generation in PRD §5.4 keeps the first source as the
    # display anchor).
    source_id: uuid.UUID | None = None
    source_title: str | None = None
    source_type: str | None = None

    # Result pointer for completed generation tasks.
    course_id: uuid.UUID | None = None
    course_title: str | None = None

    celery_task_id: str | None = None
    cancel_requested: bool = False


class TaskListResponse(BaseModel):
    """Paginated unified task list."""

    items: list[TaskListItem] = Field(default_factory=list)
    total: int = 0
    skip: int = 0
    limit: int = 50

    # Aggregate counts so the UI can render filter chips with badges
    # (PRD §5.5) without a second round-trip.
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_status: dict[str, int] = Field(default_factory=dict)


def map_task_type(raw: str) -> TaskTypeUi | None:
    """Fold the DB ``task_type`` into the two-type UI taxonomy.

    Returns ``None`` for task types the unified queue does not surface
    (e.g. memory-pruning); the caller should drop those rows.
    """
    if raw == "source_processing":
        return "embed"
    if raw in {"course_generation", "course_regeneration"}:
        return "generate"
    return None


def map_task_status(raw: str) -> TaskStatusUi:
    """Fold ``source_tasks.status`` values into the UI taxonomy.

    The DB uses ``pending`` / ``running`` / ``progress`` / ``success`` /
    ``failure``; the UI knows ``running`` / ``queued`` / ``done`` / ``failed``.
    """
    if raw in {"running", "progress"}:
        return "running"
    if raw == "pending":
        return "queued"
    if raw == "success":
        return "done"
    return "failed"
