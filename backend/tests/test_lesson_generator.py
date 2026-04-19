"""Tests for LessonGenerator service."""

import json
import pytest
from unittest.mock import AsyncMock
from app.services.lesson_generator import LessonGenerator
from app.services.llm.base import LLMResponse, ContentBlock


class TestLessonGenerator:
    @pytest.mark.asyncio
    async def test_generates_lesson_from_subtitles(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Python Basics",
                "summary": "Introduction to Python programming",
                "sections": [{
                    "heading": "Variables",
                    "content": "Variables store data values.",
                    "timestamp": 30.0,
                    "code_snippets": [{"language": "python", "code": "x = 5", "context": "Simple assignment"}],
                    "key_concepts": ["variables", "assignment"],
                    "diagrams": [],
                    "interactive_steps": None,
                }],
            }))],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(
            subtitle_chunks=["Welcome to Python basics. Let's talk about variables. x equals 5."],
            video_title="Python Basics",
        )
        assert result.title == "Python Basics"
        assert len(result.sections) == 1
        assert result.sections[0].heading == "Variables"
        assert len(result.sections[0].code_snippets) == 1

    @pytest.mark.asyncio
    async def test_generates_mermaid_diagram(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "HTTP Request Flow",
                "summary": "How HTTP works",
                "sections": [{
                    "heading": "Request Lifecycle",
                    "content": "A request goes through several stages.",
                    "timestamp": 0.0,
                    "diagrams": [{"type": "mermaid", "title": "HTTP Flow", "content": "graph LR\n  Client-->Server-->DB"}],
                    "code_snippets": [],
                    "key_concepts": ["HTTP"],
                }],
            }))],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["HTTP request flow explanation"], "HTTP Basics")
        assert len(result.sections[0].diagrams) == 1
        assert result.sections[0].diagrams[0].type == "mermaid"

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM down")
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["some subtitle text"], "Title")
        # Should return a basic fallback lesson
        assert result.title == "Title"
        assert len(result.sections) >= 1

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text="not json at all")],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["subtitle text"], "Title")
        assert result.title == "Title"

    @pytest.mark.asyncio
    async def test_accepts_goal_keyword(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Transformer Intro",
                "summary": "Goal-aware lesson summary",
                "sections": [{
                    "heading": "Overview",
                    "content": "Transformer overview content.",
                    "timestamp": 0.0,
                    "code_snippets": [],
                    "key_concepts": ["transformer"],
                    "diagrams": [],
                    "interactive_steps": None,
                }],
            }))],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(
            subtitle_chunks=["subtitle text"],
            video_title="Transformer Intro",
            goal="overview",
        )
        assert result.title == "Transformer Intro"

    @pytest.mark.asyncio
    async def test_backfills_blocks_from_legacy_sections(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Python Basics",
                "summary": "Intro summary",
                "sections": [{
                    "heading": "Variables",
                    "content": "Variables store data values.",
                    "timestamp": 30.0,
                    "code_snippets": [],
                    "key_concepts": ["variables", "assignment"],
                    "diagrams": [],
                    "interactive_steps": None,
                }],
            }))],
            model="mock",
        )

        gen = LessonGenerator(mock_provider)
        result = await gen.generate(
            subtitle_chunks=["Welcome to Python basics."],
            video_title="Python Basics",
        )

        assert len(result.blocks) >= 2
        assert result.blocks[0].type == "intro_card"
        assert result.blocks[-1].type == "recap"

    @pytest.mark.asyncio
    async def test_backfills_blocks_from_legacy_sections(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Python Basics",
                "summary": "Intro summary",
                "sections": [{
                    "heading": "Variables",
                    "content": "Variables store data values.",
                    "timestamp": 30.0,
                    "code_snippets": [],
                    "key_concepts": ["variables", "assignment"],
                    "diagrams": [],
                    "interactive_steps": None,
                }],
            }))],
            model="mock",
        )

        gen = LessonGenerator(mock_provider)
        result = await gen.generate(
            subtitle_chunks=["Welcome to Python basics."],
            video_title="Python Basics",
        )

        assert len(result.blocks) >= 2
        assert result.blocks[0].type == "intro_card"
        assert result.blocks[-1].type == "recap"
