"""Phase-5: sentence→course front half (explore → freeze gate → plan)."""

from __future__ import annotations

import pytest

from app.agentcore.llm.client import TurnResult
from app.agentcore.tools.base import ToolCall
from app.services.orchestration.graph import GraphState
from app.services.orchestration.topologies.sentence_to_course import (
    OUTLINE_FROZEN_KEY,
    SECTIONS_KEY,
    build_sentence_course_graph,
)


class FakeExploreLLM:
    """Each explore run drafts an outline (via draft_outline) then finishes."""

    def __init__(self, outlines):
        self._outlines = outlines
        self.calls = 0

    async def stream(self, messages, *, tools=None, max_tokens=4096, temperature=0.7, bus=None, parent_message_id=None):
        outline = self._outlines[min(self.calls, len(self._outlines) - 1)]
        self.calls += 1
        return TurnResult(
            tool_calls=[
                ToolCall(id="t1", name="draft_outline", input={"sections": outline}),
                ToolCall(id="t2", name="finish", input={"decision": "done"}),
            ]
        )

    async def complete(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def _good_outline():
    return [
        {"title": "Intro", "difficulty": 1, "knowledge_points": ["k1"]},
        {"title": "Core", "difficulty": 2, "knowledge_points": ["k2"]},
    ]


async def test_explore_then_freeze_happy_path():
    llm = FakeExploreLLM([_good_outline()])
    graph = build_sentence_course_graph(llm)
    state = await graph.execute(GraphState(data={"prompt": "teach me transformers"}))

    assert state.data[OUTLINE_FROZEN_KEY] is True
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Intro", "Core"]
    assert llm.calls == 1  # passed first time, no re-explore


async def test_bad_outline_backtracks_then_freezes():
    bad = [
        {"title": "Dup", "difficulty": 1, "knowledge_points": ["k"]},
        {"title": "Dup", "difficulty": 2, "knowledge_points": ["k2"]},  # duplicate title
    ]
    llm = FakeExploreLLM([bad, _good_outline()])
    graph = build_sentence_course_graph(llm)
    state = await graph.execute(
        GraphState(data={"prompt": "teach me transformers"}, backtrack_budget=2)
    )

    assert state.data[OUTLINE_FROZEN_KEY] is True
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Intro", "Core"]
    assert llm.calls == 2  # re-explored once after the freeze gate rejected the dup
    assert state.backtrack_budget == 1  # one backtrack consumed
    # The gate recorded a failing verdict before the passing one.
    assert any(not v.passed for v in state.critic_history)
