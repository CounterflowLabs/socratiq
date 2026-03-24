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


class SourceResponse(BaseModel):
    """Response model for a single source."""
    id: uuid.UUID
    type: str
    url: str | None = None
    title: str | None = None
    status: str
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    task_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    """Paginated list of sources."""
    items: list[SourceResponse]
    total: int
    skip: int
    limit: int
