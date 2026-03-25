"""Tests for exercise service."""

import json
import pytest
from unittest.mock import AsyncMock
from app.services.exercise import ExerciseService
from app.services.llm.base import LLMResponse, ContentBlock


class TestExerciseGenerate:
    @pytest.mark.asyncio
    async def test_generates_exercises(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps([{
                "type": "mcq",
                "question": "What does print() do?",
                "options": ["Displays output", "Reads input", "Deletes file", "Opens browser"],
                "answer": "Displays output",
                "explanation": "print() outputs text to the console.",
                "difficulty": 1,
                "concepts": [],
            }]))],
            model="mock",
        )
        service = ExerciseService(mock_provider)
        exercises = await service.generate_from_content("Python print function", 1, ["mcq"])
        assert len(exercises) >= 1
        assert exercises[0]["type"] == "mcq"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        service = ExerciseService(mock_provider)
        exercises = await service.generate_from_content("content", 1, ["mcq"])
        assert exercises == []


class TestExerciseEvaluate:
    @pytest.mark.asyncio
    async def test_mcq_correct(self):
        service = ExerciseService(AsyncMock())
        result = await service.evaluate_submission(
            question="Q?", answer="A", correct_answer="A", exercise_type="mcq",
        )
        assert result["score"] == 100.0

    @pytest.mark.asyncio
    async def test_mcq_wrong(self):
        service = ExerciseService(AsyncMock())
        result = await service.evaluate_submission(
            question="Q?", answer="B", correct_answer="A", exercise_type="mcq",
        )
        assert result["score"] == 0.0
