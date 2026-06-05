"""Phase-2: CourseGraph execution, gates, and bounded backtrack."""

from __future__ import annotations

import pytest

from app.agentcore.events import EventBus
from app.services.orchestration.graph import CourseGraph, GateDecision, GraphState


class RecordNode:
    def __init__(self, name: str, order_sink: list):
        self.name = name
        self._sink = order_sink

    async def run(self, state: GraphState, *, bus=None) -> GraphState:
        self._sink.append(self.name)
        state.data.setdefault("visits", {}).setdefault(self.name, 0)
        state.data["visits"][self.name] += 1
        return state


class CapturingSink:
    def __init__(self):
        self.events = []

    async def emit(self, ev):
        self.events.append(ev)


async def test_linear_execution_in_order():
    order = []
    graph = CourseGraph([RecordNode("a", order), RecordNode("b", order), RecordNode("c", order)])
    state = await graph.execute(GraphState())
    assert order == ["a", "b", "c"]
    assert state.data["visits"] == {"a": 1, "b": 1, "c": 1}


async def test_emits_step_events():
    sink = CapturingSink()
    bus = EventBus.new(sinks=[sink])
    order = []
    graph = CourseGraph([RecordNode("a", order), RecordNode("b", order)])
    await graph.execute(GraphState(), bus=bus)
    types = [(e.type.value, getattr(e, "step_name", None)) for e in sink.events]
    assert ("STEP_STARTED", "a") in types
    assert ("STEP_FINISHED", "a") in types
    assert ("STEP_STARTED", "b") in types


async def test_backtrack_once_then_continue():
    order = []

    class OnceBacktrackGate:
        def __init__(self):
            self.fired = False

        async def evaluate(self, state, *, bus=None):
            if not self.fired:
                self.fired = True
                return GateDecision(action="backtrack", target="a", feedback="redo")
            return GateDecision(action="continue")

    graph = CourseGraph(
        [RecordNode("a", order), RecordNode("b", order), RecordNode("c", order)],
        gates={"b": OnceBacktrackGate()},
    )
    state = await graph.execute(GraphState(backtrack_budget=2))
    # a, b, (backtrack) a, b, c
    assert order == ["a", "b", "a", "b", "c"]
    assert state.backtrack_budget == 1  # one consumed
    assert state.feedback["a"] == "redo"


async def test_backtrack_budget_caps_loop():
    order = []

    class AlwaysBacktrackGate:
        async def evaluate(self, state, *, bus=None):
            return GateDecision(action="backtrack", target="a", feedback="again")

    graph = CourseGraph(
        [RecordNode("a", order), RecordNode("b", order)],
        gates={"b": AlwaysBacktrackGate()},
    )
    state = await graph.execute(GraphState(backtrack_budget=2))
    # budget 2 → b backtracks twice then is forced to continue
    assert state.backtrack_budget == 0
    assert order.count("a") == 3  # initial + 2 backtracks
    assert order[-1] == "b"


def test_duplicate_node_names_rejected():
    order = []
    with pytest.raises(ValueError):
        CourseGraph([RecordNode("dup", order), RecordNode("dup", order)])
