"""Pydantic schemas for course API endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerateIncludes(BaseModel):
    """Asset toggles surfaced by the /generate step-2 config form."""
    exercises: bool = True
    lab: bool = True
    review: bool = True


class CourseGenerateRequest(BaseModel):
    """Request body for generating a course from sources.

    PRD §5.4 step 2 — surfaces only the knobs that meaningfully change
    generation output. Temperature / top-p / prompt template stay in
    Settings.
    """
    source_ids: list[uuid.UUID] = Field(..., min_length=1)
    title: str | None = None
    brief: str | None = None
    depth: int = Field(12, ge=4, le=48)
    audience: Literal["intro", "mid", "adv"] = "mid"
    tier: Literal["fast", "smart"] = "smart"
    language: Literal["source", "zh", "en"] = "source"
    includes: GenerateIncludes = Field(default_factory=GenerateIncludes)
    # PRD §10 v2 — per-source weight (0..3, default 1) so the user can
    # emphasize one source over the others during multi-source
    # synthesis. The chunk-weighting algorithm consumes this from
    # ``task.metadata_.config.source_weights``.
    source_weights: dict[uuid.UUID, float] | None = None


class CourseGenerateResponse(BaseModel):
    """202 response from async POST /courses/generate."""
    task_id: str
    source_ids: list[uuid.UUID]
    status: str  # "dispatched" | "already_dispatched"


class CourseResponse(BaseModel):
    """Response model for a course."""
    id: uuid.UUID
    title: str
    description: str | None = None
    parent_id: uuid.UUID | None = None
    regeneration_directive: str | None = None
    version_index: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceSummary(BaseModel):
    id: uuid.UUID
    url: str | None = None
    type: str


class SectionResponse(BaseModel):
    """Response model for a course section."""
    id: uuid.UUID
    title: str
    order_index: int | None = None
    source_start: str | None = None
    source_end: str | None = None
    source_id: uuid.UUID | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    difficulty: int = 1
    lesson_generation_error: str | None = None
    active_lesson_task_id: str | None = None

    model_config = {"from_attributes": True}


class RegenerateSectionLessonResponse(BaseModel):
    """202 response when a lesson regeneration task is dispatched."""
    task_id: str
    section_id: uuid.UUID
    status: str


class SectionSplitRequest(BaseModel):
    """Body for POST /sections/{id}/split.

    ``split_at_chunk_index`` is the position of the first chunk that moves
    into the newly-created section (1-based by chunk count, i.e. value 1
    keeps one chunk in the original).
    """
    split_at_chunk_index: int = Field(..., ge=1)


class SectionMergeResponse(BaseModel):
    """Result of POST /sections/{id}/merge-next."""
    surviving_section_id: uuid.UUID
    removed_section_id: uuid.UUID
    chunks_reassigned: int


class SectionSplitResponse(BaseModel):
    """Result of POST /sections/{id}/split."""
    original_section_id: uuid.UUID
    new_section_id: uuid.UUID
    chunks_in_original: int
    chunks_in_new: int


class CourseDetailResponse(BaseModel):
    """Response model for a course with sections."""
    id: uuid.UUID
    title: str
    description: str | None = None
    parent_id: uuid.UUID | None = None
    regeneration_directive: str | None = None
    version_index: int = 1
    active_regeneration_task_id: str | None = None
    sources: list[SourceSummary] = Field(default_factory=list)
    sections: list[SectionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RegenerateCourseRequest(BaseModel):
    """Request body for regenerating a course."""
    directive: str | None = Field(default=None, max_length=1000)


class RegenerateCourseResponse(BaseModel):
    """Response from POST /courses/{id}/regenerate."""
    task_id: str
    parent_course_id: uuid.UUID


class CourseListResponse(BaseModel):
    """Paginated list of courses."""
    items: list[CourseResponse]
    total: int
    skip: int
    limit: int


class CourseProgressResponse(BaseModel):
    """Aggregate progress for a course's generation/regeneration tasks."""

    course_id: uuid.UUID
    parent_course_id: uuid.UUID | None = None
    active_regeneration_task_id: str | None = None
    tasks: list[Any] = Field(default_factory=list)
