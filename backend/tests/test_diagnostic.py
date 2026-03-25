"""Tests for diagnostic service."""

import json
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock

from app.services.diagnostic import DiagnosticService
from app.services.llm.base import LLMResponse, ContentBlock


class TestDiagnosticGenerate:
    @pytest.mark.asyncio
    async def test_generates_questions_from_concepts(self):
        cid = str(uuid4())
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps([{
                "id": "q1", "concept_id": cid,
                "question": "What is recursion?",
                "options": ["A loop", "A function calling itself", "A variable", "A class"],
                "correct_index": 1, "difficulty": 2,
            }]))],
            model="mock",
        )
        service = DiagnosticService(mock_provider)
        questions = await service.generate(
            concepts=[{"id": cid, "name": "Recursion", "description": "A function that calls itself"}],
            count=1,
        )
        assert len(questions) == 1
        assert questions[0].question == "What is recursion?"
        assert len(questions[0].options) == 4

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        service = DiagnosticService(mock_provider)
        questions = await service.generate(
            concepts=[{"id": str(uuid4()), "name": "X", "description": ""}],
            count=1,
        )
        assert questions == []


class TestDiagnosticEvaluate:
    def test_all_correct_returns_advanced(self):
        service = DiagnosticService(AsyncMock())
        questions = [
            {"id": "q1", "correct_index": 1, "difficulty": 3, "concept_name": "X"},
            {"id": "q2", "correct_index": 0, "difficulty": 3, "concept_name": "Y"},
        ]
        answers = [
            {"question_id": "q1", "selected_answer": 1},
            {"question_id": "q2", "selected_answer": 0},
        ]
        result = service.evaluate(questions, answers)
        assert result.level == "advanced"
        assert result.score == 100.0
        assert "X" in result.mastered_concepts
        assert "Y" in result.mastered_concepts

    def test_none_correct_returns_beginner(self):
        service = DiagnosticService(AsyncMock())
        questions = [{"id": "q1", "correct_index": 1, "difficulty": 2, "concept_name": "X"}]
        answers = [{"question_id": "q1", "selected_answer": 0}]
        result = service.evaluate(questions, answers)
        assert result.level == "beginner"
        assert result.score == 0.0
        assert "X" in result.gaps

    def test_partial_correct_returns_intermediate(self):
        service = DiagnosticService(AsyncMock())
        questions = [
            {"id": "q1", "correct_index": 1, "concept_name": "A"},
            {"id": "q2", "correct_index": 0, "concept_name": "B"},
        ]
        answers = [
            {"question_id": "q1", "selected_answer": 1},
            {"question_id": "q2", "selected_answer": 2},
        ]
        result = service.evaluate(questions, answers)
        assert result.level == "intermediate"
        assert result.score == 50.0
