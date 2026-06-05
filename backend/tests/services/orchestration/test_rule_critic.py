"""Phase-2: RuleCritic deterministic checks."""

from __future__ import annotations

import pytest

from app.services.orchestration.critic import RuleCritic, SECTIONS_KEY
from app.services.orchestration.graph import GraphState


def _state(sections):
    return GraphState(data={SECTIONS_KEY: sections})


def _good_section(title, difficulty):
    return {
        "title": title,
        "difficulty": difficulty,
        "knowledge_points": ["kp"],
        "has_practice": True,
    }


async def test_clean_outline_passes():
    state = _state([_good_section("A", 1), _good_section("B", 2), _good_section("C", 2)])
    verdict = await RuleCritic().evaluate(state)
    assert verdict.passed
    assert verdict.action == "accept"
    assert verdict.scores["difficulty_progression"] == 1.0


async def test_difficulty_regression_flagged():
    state = _state([_good_section("A", 3), _good_section("B", 1)])
    verdict = await RuleCritic(target_node="plan").evaluate(state)
    assert not verdict.passed
    assert verdict.action == "backtrack"
    assert verdict.target_node == "plan"
    assert "难度" in verdict.feedback
    assert verdict.scores["difficulty_progression"] < 1.0


async def test_missing_knowledge_points_flagged():
    sections = [_good_section("A", 1), {"title": "B", "difficulty": 1, "knowledge_points": [], "has_practice": False}]
    verdict = await RuleCritic().evaluate(_state(sections))
    assert not verdict.passed
    assert "知识点" in verdict.feedback
    assert verdict.scores["knowledge_points"] == 0.5


async def test_quiz_coverage_flagged():
    sections = [
        _good_section("A", 1),
        {"title": "B", "difficulty": 1, "knowledge_points": ["x"], "has_practice": False},
    ]
    verdict = await RuleCritic().evaluate(_state(sections))
    assert not verdict.passed
    assert "测验" in verdict.feedback
    assert verdict.scores["quiz_coverage"] == 0.5


async def test_duplicate_titles_flagged():
    state = _state([_good_section("Same", 1), _good_section("Same", 2)])
    verdict = await RuleCritic().evaluate(state)
    assert not verdict.passed
    assert "重复" in verdict.feedback


async def test_empty_sections_accepts():
    verdict = await RuleCritic().evaluate(GraphState())
    assert verdict.passed


async def test_model_critic_parses_verdict():
    from types import SimpleNamespace

    from app.services.orchestration.critic import ModelCritic

    class FakeLLM:
        async def complete(self, messages, *, validator=None, **kw):
            parsed = validator('{"passed": false, "feedback": "难度跳变"}')
            return SimpleNamespace(parsed=parsed)

    state = _state([_good_section("A", 1)])
    verdict = await ModelCritic(FakeLLM(), target_node="plan").evaluate(state)
    assert not verdict.passed
    assert verdict.action == "backtrack"
    assert verdict.feedback == "难度跳变"


async def test_model_critic_falls_back_to_rule_on_llm_failure():
    from app.services.orchestration.critic import ModelCritic

    class BoomLLM:
        async def complete(self, *a, **k):
            raise RuntimeError("llm down")

    # Clean outline → RuleCritic fallback should pass.
    state = _state([_good_section("A", 1), _good_section("B", 2)])
    verdict = await ModelCritic(BoomLLM()).evaluate(state)
    assert verdict.passed
