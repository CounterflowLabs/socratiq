"""Pydantic schemas for course API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CourseGenerateRequest(BaseModel):
    """Request body for generating a course from sources."""
    source_ids: list[uuid.UUID] = Field(..., min_length=1)
    title: str | None = None


class CourseResponse(BaseModel):
    """Response model for a course."""
    id: uuid.UUID
    title: str
    description: str | None = None
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

    model_config = {"from_attributes": True}


class CourseDetailResponse(BaseModel):
    """Response model for a course with sections."""
    id: uuid.UUID
    title: str
    description: str | None = None
    sources: list[SourceSummary] = Field(default_factory=list)
    sections: list[SectionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseListResponse(BaseModel):
    """Paginated list of courses."""
    items: list[CourseResponse]
    total: int
    skip: int
    limit: int
