"""Structured lesson block schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class ConceptLink(BaseModel):
    """A linked concept reference in a lesson block."""

    label: str
    description: str | None = None


class LessonBlock(BaseModel):
    """A rendered block in the new lesson surface."""

    type: Literal[
        "intro_card",
        "prose",
        "diagram",
        "code_example",
        "concept_relation",
        "practice_trigger",
        "recap",
        "next_step",
    ]
    title: str | None = None
    body: str | None = None
    concepts: list[ConceptLink] = Field(default_factory=list)
    code: str | None = None
    language: str | None = None
    diagram_type: str | None = None
    diagram_content: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class TeachingAssetPlan(BaseModel):
    """Planner output for lesson study surfaces."""

    lab_mode: Literal["inline", "none"]
    graph_mode: Literal["inline_and_overview", "overview_only"]
    study_surface: Literal["reader"] = "reader"
