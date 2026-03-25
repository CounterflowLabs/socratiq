"""Pydantic schemas for structured lesson content."""

from pydantic import BaseModel, Field


class CodeSnippet(BaseModel):
    language: str = "python"
    code: str
    context: str = ""


class Diagram(BaseModel):
    type: str = "mermaid"  # "mermaid" | "comparison"
    title: str
    content: str  # Mermaid syntax or JSON


class Step(BaseModel):
    label: str
    detail: str
    code: str | None = None


class StepByStep(BaseModel):
    title: str
    steps: list[Step]


class LessonSection(BaseModel):
    heading: str
    content: str
    timestamp: float = 0.0
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    diagrams: list[Diagram] = Field(default_factory=list)
    interactive_steps: StepByStep | None = None


class LessonContent(BaseModel):
    title: str
    summary: str
    sections: list[LessonSection]
