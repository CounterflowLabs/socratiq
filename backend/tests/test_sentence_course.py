"""Unit tests for the SOURCE-LESS sentence→course back half.

Mock-based, no network: the LLM provider is an ``AsyncMock`` (mirroring
``tests/services/llm/test_runtime.py``) and ``fill_sentence_course`` is driven
by a stub generator so we can assert parallelism + per-section degradation
without a real model.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.lesson import LessonContent
from app.services.llm.base import ContentBlock, LLMResponse, TokenUsage
from app.services.orchestration.topologies.sentence_to_course import (
    fill_sentence_course,
)
from app.services.sentence_lesson_generator import (
    LessonGenerationError,
    SentenceLessonGenerator,
)


# --- helpers --------------------------------------------------------------


def _provider(model_id: str = "test-model") -> AsyncMock:
    """AsyncMock LLMProvider with a sync ``model_id()`` (see test_runtime.py)."""
    p = AsyncMock()
    p.model_id = MagicMock(return_value=model_id)
    return p


def _response(text: str) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=text)],
        model="mock",
        usage=TokenUsage(input_tokens=50, output_tokens=120),
    )


def _valid_lesson_json(title: str = "二分查找") -> str:
    return json.dumps(
        {
            "title": title,
            "summary": "一句话总结。",
            "blocks": [
                {"type": "intro_card", "title": "钩子", "body": "为什么有序数组能这么快？"},
                {
                    "type": "prose",
                    "title": "核心机制",
                    "body": "每一步把搜索区间砍半，所以是对数时间。" * 4,
                },
                {"type": "recap", "title": "回顾", "body": "区间减半是关键。"},
                {"type": "next_step", "title": "下一步", "body": "看看插入位置。"},
            ],
        },
        ensure_ascii=False,
    )


# --- SentenceLessonGenerator ----------------------------------------------


class TestSentenceLessonGenerator:
    async def test_returns_valid_lesson_with_blocks(self):
        provider = _provider()
        provider.chat.return_value = _response(_valid_lesson_json())

        gen = SentenceLessonGenerator(provider)
        lesson = await gen.generate(
            section_title="二分查找",
            knowledge_points=["有序前提", "区间减半", "时间复杂度"],
            difficulty=2,
            target_language="zh-CN",
        )

        assert isinstance(lesson, LessonContent)
        assert lesson.title == "二分查找"
        assert len(lesson.blocks) == 4
        types = [b.type for b in lesson.blocks]
        assert types[0] == "intro_card"
        assert "recap" in types and "next_step" in types
        # One LLM call, no source payload — the prompt is built from the outline.
        provider.chat.assert_awaited_once()
        sent = provider.chat.await_args.kwargs["messages"][0].content
        assert "二分查找" in sent
        assert "区间减半" in sent  # knowledge points injected

    async def test_drops_bogus_block_types(self):
        bad = json.dumps(
            {
                "title": "t",
                "summary": "",
                "blocks": [
                    {"type": "intro_card", "title": "h", "body": "hook"},
                    {"type": "totally_made_up", "title": "x", "body": "nope"},
                    {"type": "recap", "title": "r", "body": "synth"},
                ],
            },
            ensure_ascii=False,
        )
        provider = _provider()
        provider.chat.return_value = _response(bad)

        gen = SentenceLessonGenerator(provider)
        lesson = await gen.generate(
            section_title="t",
            knowledge_points=["a"],
            difficulty=1,
            target_language="en",
        )

        kinds = [b.type for b in lesson.blocks]
        assert "totally_made_up" not in kinds
        assert kinds == ["intro_card", "recap"]

    async def test_defaults_title_from_section_when_missing(self):
        no_title = json.dumps(
            {"blocks": [{"type": "prose", "title": "p", "body": "x" * 60}]},
            ensure_ascii=False,
        )
        provider = _provider()
        provider.chat.return_value = _response(no_title)

        gen = SentenceLessonGenerator(provider)
        lesson = await gen.generate(
            section_title="梯度下降",
            knowledge_points=[],
            difficulty=3,
            target_language="zh-CN",
        )
        assert lesson.title == "梯度下降"

    async def test_retries_once_on_bad_json_then_succeeds(self):
        provider = _provider()
        provider.chat.side_effect = [
            _response("this is not json at all"),
            _response(_valid_lesson_json("重试成功")),
        ]

        gen = SentenceLessonGenerator(provider)
        lesson = await gen.generate(
            section_title="重试成功",
            knowledge_points=["x"],
            difficulty=1,
            target_language="zh-CN",
        )
        assert lesson.title == "重试成功"
        assert provider.chat.await_count == 2

    async def test_raises_lesson_generation_error_after_exhausted_retry(self):
        provider = _provider()
        provider.chat.return_value = _response("never valid json")

        gen = SentenceLessonGenerator(provider)
        with pytest.raises(LessonGenerationError):
            await gen.generate(
                section_title="x",
                knowledge_points=["y"],
                difficulty=1,
                target_language="zh-CN",
            )


# --- fill_sentence_course --------------------------------------------------


class _StubGenerator:
    """Records calls and returns a trivial LessonContent per section."""

    def __init__(self, *, gate: asyncio.Event | None = None, fail_titles=()):
        self.calls: list[dict] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._gate = gate
        self._fail = set(fail_titles)

    async def generate(self, **kwargs) -> LessonContent:
        self.calls.append(kwargs)
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self._gate is not None:
                # Block until released so the test can prove all sections are
                # in-flight simultaneously (i.e. asyncio.gather, not serial).
                await self._gate.wait()
            else:
                await asyncio.sleep(0)
            if kwargs["section_title"] in self._fail:
                raise RuntimeError("boom")
            return LessonContent(
                title=kwargs["section_title"],
                summary="",
                blocks=[
                    {"type": "prose", "title": "p", "body": "body " * 20},
                ],
            )
        finally:
            self.concurrent -= 1


def _sections() -> list[dict]:
    return [
        {"title": "A", "difficulty": 1, "knowledge_points": ["a1", "a2"]},
        {"title": "B", "difficulty": 2, "knowledge_points": ["b1"]},
        {"title": "C", "difficulty": 3, "knowledge_points": []},
    ]


class TestFillSentenceCourse:
    async def test_one_lesson_per_section_in_order(self):
        gen = _StubGenerator()
        out = await fill_sentence_course(
            gen, _sections(), target_language="zh-CN"
        )

        assert [e["title"] for e in out] == ["A", "B", "C"]
        for entry in out:
            assert entry["lesson"] is not None
            assert entry["lesson"]["blocks"]  # dumped dict, not the model
            assert "error" not in entry
        assert len(gen.calls) == 3

    async def test_runs_in_parallel(self):
        gate = asyncio.Event()
        gen = _StubGenerator(gate=gate)

        task = asyncio.create_task(
            fill_sentence_course(gen, _sections(), target_language="zh-CN")
        )
        # Let all three coroutines reach the gate before releasing it.
        for _ in range(50):
            await asyncio.sleep(0)
            if gen.max_concurrent >= 3:
                break
        assert gen.max_concurrent == 3, "sections were not generated concurrently"
        gate.set()
        out = await task
        assert len(out) == 3

    async def test_wires_previous_and_next_titles(self):
        gen = _StubGenerator()
        await fill_sentence_course(gen, _sections(), target_language="en")

        by_title = {c["section_title"]: c for c in gen.calls}
        assert by_title["A"]["previous_section_title"] is None
        assert by_title["A"]["next_section_title"] == "B"
        assert by_title["B"]["previous_section_title"] == "A"
        assert by_title["B"]["next_section_title"] == "C"
        assert by_title["C"]["previous_section_title"] == "B"
        assert by_title["C"]["next_section_title"] is None
        # difficulty + knowledge_points forwarded verbatim.
        assert by_title["A"]["difficulty"] == 1
        assert by_title["A"]["knowledge_points"] == ["a1", "a2"]

    async def test_single_section_failure_degrades_only_that_section(self):
        gen = _StubGenerator(fail_titles={"B"})
        out = await fill_sentence_course(
            gen, _sections(), target_language="zh-CN"
        )

        assert len(out) == 3
        ok = {e["title"]: e for e in out}
        assert ok["A"]["lesson"] is not None
        assert ok["C"]["lesson"] is not None
        # B degraded: no lesson, error recorded — the course still assembles.
        assert ok["B"]["lesson"] is None
        assert "boom" in ok["B"]["error"]

    async def test_empty_sections_returns_empty(self):
        gen = _StubGenerator()
        out = await fill_sentence_course(gen, [], target_language="zh-CN")
        assert out == []
        assert gen.calls == []
