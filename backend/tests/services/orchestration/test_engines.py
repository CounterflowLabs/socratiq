"""Phase-2: ReActNode (finish-driven) and PlanAndExecute (batch + re-plan)."""

from __future__ import annotations

import pytest

from app.agentcore.llm.client import TurnResult
from app.agentcore.tools.base import ToolCall
from app.services.orchestration.critic import CriticVerdict
from app.services.orchestration.graph import GraphState
from app.services.orchestration.plan_execute import Plan, PlanAndExecute
from app.services.orchestration.react_node import ReActNode


class FinishingLLM:
    """Fake LLMClient whose first turn calls finish(decision), then stops."""

    def __init__(self, decision: str, reason: str = "because"):
        self._decision = decision
        self._reason = reason
        self.calls = 0

    async def stream(self, messages, *, tools=None, max_tokens=4096, temperature=0.7, bus=None, parent_message_id=None):
        self.calls += 1
        return TurnResult(
            text="",
            tool_calls=[
                ToolCall(id="tc1", name="finish", input={"decision": self._decision, "reason": self._reason})
            ],
            provider_used="fake",
        )

    async def complete(self, *a, **k):  # pragma: no cover - unused
        raise NotImplementedError


async def test_react_node_records_finish_decision():
    node = ReActNode(
        name="boundary",
        llm=FinishingLLM("recut", "boundary looks wrong"),
        system_prompt="You judge chapter boundaries.",
        context_builder=lambda s: "Here are the buckets: ...",
        decisions=("accept", "recut"),
        result_key="boundary.decision",
    )
    state = await node.run(GraphState())
    assert state.data["boundary.decision"] == {
        "decision": "recut",
        "reason": "boundary looks wrong",
    }


async def test_react_node_defaults_when_no_finish():
    class NoToolLLM:
        async def stream(self, messages, **k):
            return TurnResult(text="thinking out loud", tool_calls=[], provider_used="fake")

        async def complete(self, *a, **k):
            raise NotImplementedError

    node = ReActNode(
        name="kp",
        llm=NoToolLLM(),
        system_prompt="judge",
        context_builder=lambda s: "ctx",
        decisions=("accept", "revise"),
        default_decision="accept",
    )
    state = await node.run(GraphState())
    assert state.data["kp.decision"]["decision"] == "accept"


class DoublingPlanner:
    async def plan(self, state, *, bus=None):
        return Plan(tasks=[1, 2, 3])


class DoublingExecutor:
    async def execute(self, task, state, *, bus=None):
        return task * 2


async def test_plan_and_execute_runs_batch():
    engine = PlanAndExecute(DoublingPlanner(), DoublingExecutor(), parallel=True)
    results = await engine.run(GraphState())
    assert sorted(results) == [2, 4, 6]


async def test_plan_and_execute_replans_on_critic_fail():
    class FlakyCritic:
        def __init__(self):
            self.calls = 0

        async def evaluate(self, state, *, bus=None):
            self.calls += 1
            passed = self.calls >= 2  # fail first, pass second
            return CriticVerdict(passed=passed, action="accept" if passed else "backtrack", feedback="fix it")

    critic = FlakyCritic()

    class CountingPlanner(DoublingPlanner):
        def __init__(self):
            self.plans = 0

        async def plan(self, state, *, bus=None):
            self.plans += 1
            return Plan(tasks=[1])

    planner = CountingPlanner()
    engine = PlanAndExecute(planner, DoublingExecutor(), critic=critic, max_replans=1)
    results = await engine.run(GraphState())
    assert results == [2]
    assert planner.plans == 2  # re-planned once
    assert critic.calls == 2
