"""Pydantic schemas for lab responses."""

from pydantic import BaseModel


class LabResponse(BaseModel):
    id: str
    section_id: str
    title: str
    description: str
    language: str
    starter_code: dict[str, str]
    test_code: dict[str, str]
    run_instructions: str
    confidence: float
