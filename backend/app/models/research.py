"""Schemas for lesson research enrichment."""

from typing import Literal

from pydantic import BaseModel, Field


class ResearchCard(BaseModel):
    """A vetted external reference that can enrich one lesson section."""

    type: Literal[
        "frontier_note",
        "engineering_note",
        "further_reading",
        "misconception_boundary",
    ]
    title: str
    source_title: str
    url: str
    published_at: str | None = None
    source_type: Literal[
        "paper",
        "research_blog",
        "technical_report",
        "code_repo",
        "documentation",
        "article",
    ]
    relevance: str
    use_as: Literal[
        "boundary_or_extension",
        "engineering_context",
        "further_reading",
        "practice_context",
    ]
    concepts: list[str] = Field(default_factory=list)
    risk_note: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)

