"""Unit tests for the video→course outline topology.

Cover the OutlinePlannerNode (consolidation, anti-fragmentation guard,
partition validation, warm-start floor) and the graph's critic-backtrack loop.
The LLM is a stub exposing ``complete(...)`` like RouterLLMClient — no network.
"""

import json
from dataclasses import dataclass

import pytest

from app.services.llm.runtime import LLMValidationError, ValidationFailed
from app.services.orchestration.graph import GraphState
from app.services.orchestration.topologies.video_to_course import (
    CHUNK_SUMMARIES_KEY,
    SECTIONS_KEY,
    TITLE_KEY,
    WARM_START_KEY,
    OutlinePlannerNode,
    build_video_course_graph,
    split_oversized_sections,
)


@dataclass
class _Result:
    parsed: object
    input_tokens: int = 0
    output_tokens: int = 0


class _StubLLM:
    """Mimics RouterLLMClient.complete: runs the validator on a scripted text.

    ``responses`` is a list of raw model texts returned in order across calls.
    The validator runs exactly as the real runtime would; if it raises
    ValidationFailed on the last scripted response, we surface
    LLMValidationError (mirroring max_validation_retries exhaustion).
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages, *, validator=None, max_validation_retries=1, **kw):
        self.calls += 1
        text = self._responses.pop(0) if self._responses else "{}"
        if validator is None:
            return _Result(parsed=text)
        try:
            return _Result(parsed=validator(text))
        except ValidationFailed as exc:
            raise LLMValidationError(str(exc), 1, input_tokens=0, output_tokens=0) from exc


def _chunks(n: int) -> list[dict]:
    return [
        {"idx": i, "topic": f"Topic {i}", "summary": f"Summary of part {i}"}
        for i in range(n)
    ]


def _outline_json(sections: list[dict]) -> str:
    return json.dumps({"sections": sections})


def _state(n: int, *, warm=None, title="Test Course") -> GraphState:
    data = {CHUNK_SUMMARIES_KEY: _chunks(n), TITLE_KEY: title}
    if warm is not None:
        data[WARM_START_KEY] = warm
    return GraphState(data=data)


# --- consolidation happy path ---------------------------------------------


@pytest.mark.asyncio
async def test_planner_consolidates_chunks_into_outline():
    # 6 chunks → 2 coherent sections covering all indices.
    sections = [
        {"title": "Foundations", "difficulty": 1, "knowledge_points": ["basics"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Application", "difficulty": 2, "knowledge_points": ["applied"],
         "source_chunk_indices": [3, 4, 5]},
    ]
    node = OutlinePlannerNode(llm=_StubLLM([_outline_json(sections)]))
    state = await node.run(_state(6))

    out = state.data[SECTIONS_KEY]
    assert [s["title"] for s in out] == ["Foundations", "Application"]
    assert all(s["has_practice"] for s in out)
    # Every chunk covered exactly once.
    covered = [i for s in out for i in s["source_chunk_indices"]]
    assert sorted(covered) == list(range(6))


def test_build_messages_pins_title_language():
    # The planner must tell the model to write titles in target_language while
    # keeping knowledge_points canonical English lower_snake_case.
    node = OutlinePlannerNode(llm=_StubLLM([]), target_language="en")
    state = _state(4)
    chunk_summaries = list(state.data[CHUNK_SUMMARIES_KEY])
    messages = node._build_messages(state, chunk_summaries, len(chunk_summaries))

    blob = "\n".join(m.content for m in messages)
    assert "en" in blob  # the target language string is present
    # System prompt carries the language directive (rendered, no stray braces).
    system = next(m.content for m in messages if m.role == "system")
    assert "en" in system
    assert "{target_language}" not in system  # template was formatted
    assert "{{" not in system and "}}" not in system  # JSON braces un-escaped
    # knowledge_points must stay English lower_snake_case (not translated).
    assert "lower_snake_case" in blob


def test_build_messages_defaults_to_zh_cn():
    # Default target_language preserves the original Chinese-titles behavior.
    node = OutlinePlannerNode(llm=_StubLLM([]))
    state = _state(4)
    chunk_summaries = list(state.data[CHUNK_SUMMARIES_KEY])
    messages = node._build_messages(state, chunk_summaries, len(chunk_summaries))
    blob = "\n".join(m.content for m in messages)
    assert "zh-CN" in blob


@pytest.mark.asyncio
async def test_single_chunk_skips_llm():
    llm = _StubLLM([])  # must not be called
    node = OutlinePlannerNode(llm=llm)
    state = await node.run(_state(1))
    assert llm.calls == 0
    assert len(state.data[SECTIONS_KEY]) == 1
    assert state.data[SECTIONS_KEY][0]["source_chunk_indices"] == [0]


# --- validator guards ------------------------------------------------------


@pytest.mark.asyncio
async def test_anti_fragmentation_guard_rejects_per_chunk_outline():
    # Planner returns one section per chunk for 20 chunks → over the cap → the
    # validator rejects; with no further scripted response the node falls back
    # to the warm-start floor rather than emitting 20 sections.
    per_chunk = [
        {"title": f"S{i}", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [i]}
        for i in range(20)
    ]
    node = OutlinePlannerNode(
        llm=_StubLLM([_outline_json(per_chunk)]), max_sections=12
    )
    warm = [{"topic": "A", "chunk_indices": list(range(10))},
            {"topic": "B", "chunk_indices": list(range(10, 20))}]
    state = await node.run(_state(20, warm=warm))
    out = state.data[SECTIONS_KEY]
    assert len(out) <= 12
    assert len(out) == 2  # fell back to the 2 warm-start buckets
    assert sorted(i for s in out for i in s["source_chunk_indices"]) == list(range(20))


def _run_validator(node: OutlinePlannerNode, payload: dict, n: int):
    return node._validate(json.dumps(payload), n)


def test_validator_rejects_uncovered_chunks():
    node = OutlinePlannerNode(llm=_StubLLM([]))
    with pytest.raises(ValidationFailed, match="chunks_uncovered"):
        _run_validator(node, {"sections": [
            {"title": "Only", "difficulty": 1, "knowledge_points": ["k"],
             "source_chunk_indices": [0, 1]},
        ]}, n=4)


def test_validator_rejects_reused_chunk():
    node = OutlinePlannerNode(llm=_StubLLM([]))
    with pytest.raises(ValidationFailed, match="chunk_index_reused"):
        _run_validator(node, {"sections": [
            {"title": "A", "difficulty": 1, "knowledge_points": ["k"],
             "source_chunk_indices": [0, 1]},
            {"title": "B", "difficulty": 2, "knowledge_points": ["k"],
             "source_chunk_indices": [1, 2]},
        ]}, n=3)


def test_validator_rejects_non_contiguous_section():
    node = OutlinePlannerNode(llm=_StubLLM([]))
    with pytest.raises(ValidationFailed, match="not_contiguous"):
        _run_validator(node, {"sections": [
            {"title": "Scattered", "difficulty": 1, "knowledge_points": ["k"],
             "source_chunk_indices": [0, 1, 3]},  # gap at 2
            {"title": "Other", "difficulty": 2, "knowledge_points": ["k"],
             "source_chunk_indices": [2]},
        ]}, n=4)


def test_validator_clamps_difficulty_and_sorts_by_source_order():
    node = OutlinePlannerNode(llm=_StubLLM([]))
    out = _run_validator(node, {"sections": [
        {"title": "Late", "difficulty": 9, "knowledge_points": ["k"],
         "source_chunk_indices": [2, 3]},
        {"title": "Early", "difficulty": 0, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1]},
    ]}, n=4)
    assert [s["title"] for s in out] == ["Early", "Late"]  # sorted by first idx
    assert [s["difficulty"] for s in out] == [1, 5]  # clamped into 1..5


# --- graph: critic gate drives a backtrack ---------------------------------


# --- budget-aware oversized-section split ---------------------------------


def test_split_oversized_section_into_parts():
    # One section of 6 chunks @ 1000 tokens each = 6000, cap 2500 → 3 parts.
    sections = [
        {"title": "Big", "difficulty": 2, "knowledge_points": ["k"],
         "has_practice": True, "source_chunk_indices": [0, 1, 2, 3, 4, 5]},
    ]
    counts = [1000] * 6
    out = split_oversized_sections(sections, counts, cap_tokens=2500)
    assert len(out) == 3
    # Contiguous, complete, ordered coverage preserved.
    covered = [i for s in out for i in s["source_chunk_indices"]]
    assert covered == list(range(6))
    assert all(s["difficulty"] == 2 for s in out)
    assert all("部分" in s["title"] for s in out)
    # Each part fits the cap (≤2500 → ≤2 chunks of 1000).
    assert all(len(s["source_chunk_indices"]) <= 2 for s in out)


def test_split_leaves_within_budget_sections_untouched():
    sections = [
        {"title": "Small", "difficulty": 1, "knowledge_points": ["k"],
         "has_practice": True, "source_chunk_indices": [0, 1]},
    ]
    out = split_oversized_sections(sections, [500, 500], cap_tokens=2500)
    assert out == sections  # unchanged object/content


def test_split_keeps_single_oversized_chunk_as_one_part():
    # A single chunk that alone exceeds the cap can't be split further.
    sections = [
        {"title": "Huge", "difficulty": 1, "knowledge_points": [],
         "has_practice": True, "source_chunk_indices": [0]},
    ]
    out = split_oversized_sections(sections, [9999], cap_tokens=2500)
    assert len(out) == 1
    assert out[0]["source_chunk_indices"] == [0]


@pytest.mark.asyncio
async def test_graph_backtracks_on_duplicate_titles_then_succeeds():
    # First outline has duplicate titles → RuleCritic backtracks to the
    # planner; second outline is clean → graph completes.
    bad = _outline_json([
        {"title": "Dup", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Dup", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    good = _outline_json([
        {"title": "Intro", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Deeper", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    llm = _StubLLM([bad, good])
    graph = build_video_course_graph(llm)
    state = await graph.execute(_state(6))

    titles = [s["title"] for s in state.data[SECTIONS_KEY]]
    assert titles == ["Intro", "Deeper"]
    assert llm.calls == 2  # planned twice: original + one backtrack
    # A critic verdict was recorded for the rejected first outline.
    assert any(not v.passed for v in state.critic_history)


@pytest.mark.asyncio
async def test_graph_backtrack_is_budget_bounded():
    # Always-duplicate outline: the gate keeps wanting to backtrack but the
    # budget caps re-plans; the graph still terminates with the last outline.
    dup = _outline_json([
        {"title": "Same", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Same", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    llm = _StubLLM([dup, dup, dup, dup, dup])
    graph = build_video_course_graph(llm)
    state = await graph.execute(_state(6))  # GraphState.backtrack_budget defaults to 2
    # 1 initial plan + 2 backtracks = 3 planner calls, then budget exhausted.
    assert llm.calls == 3
    assert state.data[SECTIONS_KEY]  # still produced an outline


# --- ReAct re-cut node: boundary judgment drives a backtrack ---------------
#
# The re-cut node uses an agentcore ``LLMClient`` (``.stream`` + a ToolExecutor
# running an inspect tool then ``finish``) — NOT the planner's ``.complete``
# stub. So its stub mirrors ``FinishingLLM`` in tests/services/orchestration/
# test_engines.py: each ``stream`` turn returns a ``finish`` tool call (in the
# loop's ``stop_tools``), so one turn = one ReAct-node decision. We script the
# decision per ReAct-node invocation to exercise recut→backtrack then accept.


class _RecutStubLLM:
    """Fake agentcore LLMClient for the re-cut ReActNode.

    ``decisions`` are returned in order, one per ReAct-node run (each run is a
    single ``stream`` turn that calls ``finish`` and stops the loop). After the
    list is exhausted it keeps returning the last decision, so it's safe even if
    the node runs more times than scripted.
    """

    def __init__(self, decisions: list[str], reason: str = "boundary defect") -> None:
        self._decisions = list(decisions)
        self._reason = reason
        self.calls = 0

    async def stream(self, messages, *, tools=None, max_tokens=4096,
                     temperature=0.7, bus=None, parent_message_id=None):
        from app.agentcore.llm.client import TurnResult
        from app.agentcore.tools.base import ToolCall

        idx = min(self.calls, len(self._decisions) - 1) if self._decisions else 0
        decision = self._decisions[idx] if self._decisions else "accept"
        self.calls += 1
        return TurnResult(
            text="",
            tool_calls=[ToolCall(
                id=f"tc{self.calls}",
                name="finish",
                input={"decision": decision, "reason": self._reason},
            )],
            provider_used="fake",
        )

    async def complete(self, *a, **k):  # pragma: no cover - planner uses the other stub
        raise NotImplementedError


@pytest.mark.asyncio
async def test_inspect_tool_exposes_outline_with_chunk_topics():
    # The inspect tool projects sections + their covered chunk topics/summaries
    # (the semantic signal the rule critic ignores) so the judge can reason over
    # boundaries. Read-only: it must not mutate state.
    from app.agentcore.tools.base import ToolContext
    from app.services.orchestration.topologies.video_to_course import OutlineInspectTool

    state = _state(4)
    state.data[SECTIONS_KEY] = [
        {"title": "A", "difficulty": 1, "knowledge_points": ["k"],
         "has_practice": True, "source_chunk_indices": [0, 1]},
        {"title": "B", "difficulty": 2, "knowledge_points": ["k"],
         "has_practice": True, "source_chunk_indices": [2, 3]},
    ]
    tool = OutlineInspectTool()
    result = await tool.run(ToolContext(extras={"state": state}))
    payload = json.loads(result.content)

    assert payload["section_count"] == 2
    assert [s["title"] for s in payload["sections"]] == ["A", "B"]
    first = payload["sections"][0]
    assert first["source_chunk_indices"] == [0, 1]
    assert first["chunk_count"] == 2
    # Carries the per-chunk topic so the judge sees what each section is about.
    assert [c["topic"] for c in first["chunks"]] == ["Topic 0", "Topic 1"]
    # Read-only: sections untouched.
    assert len(state.data[SECTIONS_KEY]) == 2


@pytest.mark.asyncio
async def test_recut_disabled_by_default_no_extra_node():
    # enable_recut defaults False → graph is exactly plan→critic; a clean
    # outline completes in one planner call with no recut artifacts.
    good = _outline_json([
        {"title": "Intro", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Deeper", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    planner = _StubLLM([good])
    graph = build_video_course_graph(planner)  # enable_recut defaults False
    state = await graph.execute(_state(6))

    assert planner.calls == 1
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Intro", "Deeper"]
    # No recut verdict was ever written.
    from app.services.orchestration.topologies.video_to_course import RECUT_RESULT_KEY
    assert RECUT_RESULT_KEY not in state.data


@pytest.mark.asyncio
async def test_recut_recut_then_accept_backtracks_to_planner():
    # enable_recut=True: the judge says "recut" once → backtrack to the planner
    # (re-plan), then "accept" → graph completes with the SECOND outline. The
    # planner is therefore invoked twice (proof the backtrack happened) and the
    # recut judge twice (recut, then accept).
    from app.services.orchestration.topologies.video_to_course import RECUT_RESULT_KEY

    first = _outline_json([
        {"title": "Mixed", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2, 3, 4, 5]},
    ])
    second = _outline_json([
        {"title": "Part One", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Part Two", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    planner = _StubLLM([first, second])
    recut = _RecutStubLLM(["recut", "accept"], reason="拆开 Mixed：前半与后半是两个主题")
    graph = build_video_course_graph(planner, enable_recut=True, recut_llm=recut)
    state = await graph.execute(_state(6))

    # Re-cut requested a re-plan → planner ran twice; judge ran twice.
    assert planner.calls == 2
    assert recut.calls == 2
    # Final outline is the re-cut (second) outline.
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Part One", "Part Two"]
    # The planner's second call saw the judge's feedback (replayed via backtrack).
    assert "拆开 Mixed" in state.feedback.get("plan_outline", "")
    # Final recorded verdict is the accept.
    assert state.data[RECUT_RESULT_KEY]["decision"] == "accept"


@pytest.mark.asyncio
async def test_recut_accept_leaves_outline_unchanged():
    # enable_recut=True but the judge accepts on the first look → no backtrack:
    # planner runs once, the outline is exactly what it produced.
    from app.services.orchestration.topologies.video_to_course import RECUT_RESULT_KEY

    outline = _outline_json([
        {"title": "Intro", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Deeper", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    planner = _StubLLM([outline])
    recut = _RecutStubLLM(["accept"])
    graph = build_video_course_graph(planner, enable_recut=True, recut_llm=recut)
    state = await graph.execute(_state(6))

    assert planner.calls == 1  # no re-plan
    assert recut.calls == 1
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Intro", "Deeper"]
    assert state.data[RECUT_RESULT_KEY]["decision"] == "accept"
    # No backtrack feedback was written to the planner.
    assert "plan_outline" not in state.feedback


@pytest.mark.asyncio
async def test_recut_is_backtrack_budget_bounded():
    # A judge that ALWAYS says "recut" must not loop forever — the shared
    # backtrack_budget caps re-plans, then the graph terminates accepting the
    # last outline. budget defaults to 2 → 1 initial plan + 2 re-plans.
    outline = _outline_json([
        {"title": "Whole", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2, 3, 4, 5]},
    ])
    planner = _StubLLM([outline, outline, outline, outline])
    recut = _RecutStubLLM(["recut"])  # always wants a re-cut
    graph = build_video_course_graph(planner, enable_recut=True, recut_llm=recut)
    state = await graph.execute(_state(6))  # backtrack_budget defaults to 2

    assert planner.calls == 3   # 1 + 2 backtracks, then budget exhausted
    assert state.data[SECTIONS_KEY]  # still produced an outline (never blocked)


@pytest.mark.asyncio
async def test_recut_defaults_to_accept_when_judge_errors():
    # SAFETY: if the re-cut LLM raises (timeout/outage), the ReActNode swallows
    # it and defaults to "accept" — generation is never blocked, and no
    # backtrack is triggered.
    class _BoomLLM:
        calls = 0

        async def stream(self, *a, **k):
            type(self).calls += 1
            raise RuntimeError("provider down")

        async def complete(self, *a, **k):  # pragma: no cover
            raise NotImplementedError

    outline = _outline_json([
        {"title": "Intro", "difficulty": 1, "knowledge_points": ["k"],
         "source_chunk_indices": [0, 1, 2]},
        {"title": "Deeper", "difficulty": 2, "knowledge_points": ["k"],
         "source_chunk_indices": [3, 4, 5]},
    ])
    planner = _StubLLM([outline])
    graph = build_video_course_graph(planner, enable_recut=True, recut_llm=_BoomLLM())
    state = await graph.execute(_state(6))

    assert planner.calls == 1  # no re-plan despite the judge crashing
    assert [s["title"] for s in state.data[SECTIONS_KEY]] == ["Intro", "Deeper"]
