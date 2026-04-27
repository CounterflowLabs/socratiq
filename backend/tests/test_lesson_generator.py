"""Tests for LessonGenerator service."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.lesson_generator import LessonGenerator
from app.services.llm.base import ContentBlock, LLMResponse


def _mock_response(payload: dict) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=json.dumps(payload))],
        model="mock",
    )


class TestLessonGenerator:
    @pytest.mark.asyncio
    async def test_parses_block_based_response(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "Python 基础",
            "summary": "讲解 Python 变量赋值。",
            "blocks": [
                {"type": "intro_card", "title": "Python 基础", "body": "你将学到变量赋值。"},
                {
                    "type": "prose",
                    "title": "变量",
                    "body": "Python 用 = 给变量赋值。" * 5,
                    "metadata": {"timestamp": 30},
                },
                {
                    "type": "code_example",
                    "title": "赋值示例",
                    "body": "最简单的赋值。",
                    "code": "x = 5",
                    "language": "python",
                },
                {
                    "type": "concept_relation",
                    "title": "相关概念",
                    "concepts": [
                        {"label": "variable", "description": "存储值的命名容器。"},
                        {"label": "assignment", "description": "把值绑定到名字。"},
                    ],
                },
                {"type": "recap", "title": "Recap", "body": "变量用 = 赋值。"},
                {"type": "next_step", "title": "Next step", "body": "尝试函数定义。"},
            ],
        })

        gen = LessonGenerator(mock_provider)
        result = await gen.generate(
            subtitle_chunks=["Python 变量赋值"],
            video_title="Python 基础",
            target_language="zh-CN",
        )

        assert result.title == "Python 基础"
        assert [b.type for b in result.blocks] == [
            "intro_card",
            "prose",
            "code_example",
            "concept_relation",
            "recap",
            "next_step",
        ]
        assert result.blocks[2].code == "x = 5"
        assert [c.label for c in result.blocks[3].concepts] == ["variable", "assignment"]
        assert result.blocks[1].metadata["timestamp"] == 30

    @pytest.mark.asyncio
    async def test_passes_target_language_to_prompt(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "T",
            "summary": "S",
            "blocks": [{"type": "prose", "title": "x", "body": "y"}],
        })
        gen = LessonGenerator(mock_provider)
        await gen.generate(["subtitle"], "T", target_language="en")

        sent_content = mock_provider.chat.call_args.kwargs["messages"][0].content
        assert "Lesson language: en" in sent_content

    @pytest.mark.asyncio
    async def test_llm_failure_returns_single_prose_fallback(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["raw subtitle"], "Title", target_language="zh-CN")

        assert result.title == "Title"
        assert len(result.blocks) == 1
        assert result.blocks[0].type == "prose"
        assert "raw subtitle" in result.blocks[0].body

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text="not json at all")],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["subtitle text"], "Title", target_language="zh-CN")

        assert result.title == "Title"
        assert result.blocks[0].type == "prose"

    @pytest.mark.asyncio
    async def test_appends_goal_to_prompt(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = _mock_response({
            "title": "T", "summary": "S",
            "blocks": [{"type": "prose", "title": "x", "body": "y"}],
        })
        gen = LessonGenerator(mock_provider)
        await gen.generate(
            subtitle_chunks=["subtitle"],
            video_title="T",
            target_language="zh-CN",
            goal="quick overview",
        )

        sent_content = mock_provider.chat.call_args.kwargs["messages"][0].content
        assert "Learning goal: quick overview" in sent_content
