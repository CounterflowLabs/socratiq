"""Tests for LabGenerator service."""

import json
import pytest
from unittest.mock import AsyncMock
from app.services.lab_generator import LabGenerator
from app.services.llm.base import LLMResponse, ContentBlock
from app.models.lesson import CodeSnippet


class TestLabGenerator:
    @pytest.mark.asyncio
    async def test_generates_lab_from_code_snippets(self):
        mock_provider = AsyncMock()
        # First call: generate solution + starter + tests
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Build a Calculator",
                "description": "Implement basic calculator functions.",
                "language": "python",
                "starter_code": {"calculator.py": "def add(a, b):\n    # TODO: implement\n    pass"},
                "test_code": {"test_calculator.py": "from calculator import add\ndef test_add():\n    assert add(1, 2) == 3"},
                "solution_code": {"calculator.py": "def add(a, b):\n    return a + b"},
                "run_instructions": "```bash\npython -m pytest test_calculator.py -v\n```",
                "confidence": 0.8,
            }))],
            model="mock",
        )
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="def add(a, b): return a + b", context="Simple addition")],
            lesson_context="This lesson covers basic arithmetic operations in Python.",
            language="python",
        )
        assert result is not None
        assert result["title"] == "Build a Calculator"
        assert "TODO" in result["starter_code"]["calculator.py"]

    @pytest.mark.asyncio
    async def test_no_code_snippets_returns_none(self):
        gen = LabGenerator(AsyncMock())
        result = await gen.generate(code_snippets=[], lesson_context="Theory only", language="python")
        assert result is None

    @pytest.mark.asyncio
    async def test_low_confidence_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Bad Lab", "description": "x", "language": "python",
                "starter_code": {}, "test_code": {}, "solution_code": {},
                "run_instructions": "", "confidence": 0.2,
            }))],
            model="mock",
        )
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="")],
            lesson_context="", language="python",
        )
        assert result is None  # confidence < 0.3

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="")],
            lesson_context="", language="python",
        )
        assert result is None
