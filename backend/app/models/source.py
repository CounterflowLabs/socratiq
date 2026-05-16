"""Pydantic schemas for source API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    """Request body for creating a source."""
    url: str | None = None
    source_type: str | None = None
    title: str | None = None


class SourceTaskSummary(BaseModel):
    """Minimal task summary embedded on source responses."""

    id: uuid.UUID
    task_type: str
    status: str
    stage: str | None = None
    error_summary: str | None = None
    celery_task_id: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata_")

    model_config = {"from_attributes": True}


class SourceEmbed(BaseModel):
    """Embedding-side state of a source — PRD §9.

    Folds ``Source.status`` + the latest ``source_processing`` row into a
    single 5-state taxonomy the UI can render without sniffing both
    structures.
    """

    status: str  # ready | running | queued | failed | stale | cancelled
    model: str | None = None
    chunks: int | None = None
    vectors: int | None = None
    progress: float | None = None
    eta_seconds: int | None = None
    error: str | None = None
    reason: str | None = None  # populated for stale to say *why*


class SourceResponse(BaseModel):
    """Response model for a single source."""
    id: uuid.UUID
    type: str
    url: str | None = None
    title: str | None = None
    status: str
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    task_id: str | None = None
    latest_processing_task: SourceTaskSummary | None = None
    latest_course_task: SourceTaskSummary | None = None
    course_count: int = 0
    latest_course_id: uuid.UUID | None = None
    duplicate_of_source_id: uuid.UUID | None = None
    duplicate_reason: str | None = None
    # New PRD §9 sub-object. Legacy callers can keep reading the flat
    # status/latest_processing_task fields above for the duration of the
    # transition.
    embed: SourceEmbed | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    """Paginated list of sources."""
    items: list[SourceResponse]
    total: int
    skip: int
    limit: int


class SourceTaskProgress(BaseModel):
    """Per-task progress slice exposed to the frontend."""

    task_type: str
    status: str
    stage: str | None = None
    error_summary: str | None = None
    celery_task_id: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    cancel_requested: bool = False
    course_id: uuid.UUID | None = None
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceProgressResponse(BaseModel):
    """Aggregate progress for a source across its task types."""

    source_id: uuid.UUID
    source_status: str
    error: str | None = None
    course_id: uuid.UUID | None = None
    tasks: list[SourceTaskProgress] = Field(default_factory=list)
