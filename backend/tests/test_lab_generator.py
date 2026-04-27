"""Tests for LabGenerator service."""

import json
from unittest.mock import AsyncMock

import pytest

from app.models.lesson import CodeSnippet
from app.services.lab_generator import LabGenerator
from app.services.llm.base import ContentBlock, LLMResponse


def _mock_response(payload: dict) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=json.dumps(payload))],
        model="mock",
    )


class TestLabGenerator:
    @pytest.mark.asyncio
    async def test_generates_lab_from_code_snippets(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "Build a Calculator",
            "description": "Implement basic calculator functions.",
            "language": "python",
            "starter_code": {"calculator.py": "def add(a, b):\n    # TODO: implement\n    pass"},
            "test_code": {"test_calculator.py": "from calculator import add\ndef test_add():\n    assert add(1, 2) == 3"},
            "solution_code": {"calculator.py": "def add(a, b):\n    return a + b"},
            "run_instructions": "```bash\npython -m pytest test_calculator.py -v\n```",
            "confidence": 0.8,
        })
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="def add(a, b): return a + b", context="Simple addition")],
            lesson_context="This lesson covers basic arithmetic operations in Python.",
            language="python",
            target_language="zh-CN",
        )
        assert result is not None
        assert result["title"] == "Build a Calculator"
        assert "TODO" in result["starter_code"]["calculator.py"]

    @pytest.mark.asyncio
    async def test_no_code_snippets_returns_none(self):
        gen = LabGenerator(AsyncMock())
        result = await gen.generate(
            code_snippets=[],
            lesson_context="Theory only",
            language="python",
            target_language="zh-CN",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_low_confidence_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "Bad Lab", "description": "x", "language": "python",
            "starter_code": {}, "test_code": {}, "solution_code": {},
            "run_instructions": "", "confidence": 0.2,
        })
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="")],
            lesson_context="", language="python", target_language="zh-CN",
        )
        assert result is None  # confidence < 0.3

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="")],
            lesson_context="", language="python", target_language="zh-CN",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_accepts_goal_keyword(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "Build Attention Scores",
            "description": "Implement a simple attention scorer.",
            "language": "python",
            "starter_code": {"attention.py": "def score(q, k):\n    # TODO\n    pass"},
            "test_code": {"test_attention.py": "from attention import score\n\ndef test_score():\n    assert score([1], [1]) == 1"},
            "solution_code": {"attention.py": "def score(q, k):\n    return q[0] * k[0]"},
            "run_instructions": "python -m pytest -v",
            "confidence": 0.9,
        })
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="def score(q, k): return q[0] * k[0]", context="dot product")],
            lesson_context="Attention lesson",
            language="python",
            target_language="zh-CN",
            goal="apply",
        )
        assert result is not None
        assert result["title"] == "Build Attention Scores"

    @pytest.mark.asyncio
    async def test_user_directive_appears_in_prompt(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "T", "description": "d", "language": "python",
            "starter_code": {"a.py": "pass"}, "test_code": {"t.py": "pass"},
            "solution_code": {"a.py": "pass"}, "run_instructions": "x", "confidence": 0.9,
        })
        gen = LabGenerator(mock_provider)
        await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="")],
            lesson_context="ctx",
            language="python",
            target_language="en",
            user_directive="Make the lab simpler",
        )
        sent = mock_provider.chat.call_args.kwargs["messages"][0].content
        assert "Make the lab simpler" in sent
