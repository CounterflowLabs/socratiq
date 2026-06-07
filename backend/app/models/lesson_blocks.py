"""Structured lesson block schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class ConceptLink(BaseModel):
    """A linked concept reference in a lesson block."""

    label: str
    description: str | None = None


class Reference(BaseModel):
    """One further-reading citation in a ``further_reading`` block.

    ``url`` is populated ONLY for verified references (those supplied via the
    curated research supplements). When the model names a work from its own
    knowledge it must leave ``url`` empty rather than fabricate a locator — see
    the anti-hallucination rules in the lesson prompts.
    """

    title: str
    source: str | None = None  # authors / venue / publisher, e.g. "Vaswani et al., 2017"
    year: str | None = None
    kind: Literal["classic", "frontier"] = "classic"
    url: str | None = None  # verified only; never fabricated
    note: str | None = None  # one line: why it's worth reading


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
        "further_reading",
    ]
    title: str | None = None
    body: str | None = None
    concepts: list[ConceptLink] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
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
