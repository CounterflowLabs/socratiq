"""Pydantic schemas for cold-start diagnostic."""

from uuid import UUID
from pydantic import BaseModel


class DiagnosticQuestion(BaseModel):
    id: str
    concept_id: UUID
    question: str
    options: list[str]
    correct_index: int
    difficulty: int


class DiagnosticAnswer(BaseModel):
    question_id: str
    selected_answer: int
    time_spent_seconds: float = 0


class DiagnosticSubmitRequest(BaseModel):
    answers: list[DiagnosticAnswer]


class DiagnosticFullSubmitRequest(BaseModel):
    """Submit request that includes the original questions and student answers.

    Used by the diagnostic submit endpoint since questions are not stored
    server-side between generate and submit.
    """

    questions: list[dict]  # [{id, correct_index, concept_name, ...}]
    answers: list[DiagnosticAnswer]


class DiagnosticResult(BaseModel):
    level: str
    mastered_concepts: list[str]
    gaps: list[str]
    score: float
