"""CourseGraph — an ordered node pipeline with critic gates and bounded backtrack.

This is the general expression of the teaching topologies: a sequence of
``Node``s, each optionally followed by a ``Gate`` that can request a
``backtrack`` to an earlier node (e.g. a critic sending control back to the
planner). Backtracking is hard-capped by ``GraphState.backtrack_budget`` so a
failing critic can never loop forever.

Each node run is bracketed by AG-UI ``STEP_STARTED`` / ``STEP_FINISHED`` events
on the bus; backtracks emit a ``CUSTOM`` ``backtrack`` event. Deterministic
(pure-code) nodes and LLM/ReAct nodes both satisfy the same ``Node`` protocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.services.orchestration.critic import CriticVerdict

logger = logging.getLogger(__name__)

__all__ = ["GraphState", "Node", "Gate", "GateDecision", "CourseGraph"]


@dataclass
class GraphState:
    """Mutable working set threaded through the graph.

    ``data`` holds the pipeline payload (analyses, plan, outline, sections,
    lessons, …) keyed by string so nodes stay decoupled. ``feedback`` carries a
    critic's note to the node it backtracked to.
    """

    data: dict[str, Any] = field(default_factory=dict)
    critic_history: list[CriticVerdict] = field(default_factory=list)
    backtrack_budget: int = 2
    feedback: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Node(Protocol):
    name: str

    async def run(self, state: GraphState, *, bus=None) -> GraphState: ...


@dataclass
class GateDecision:
    action: Literal["continue", "backtrack"] = "continue"
    target: str | None = None
    feedback: str = ""


@runtime_checkable
class Gate(Protocol):
    async def evaluate(self, state: GraphState, *, bus=None) -> GateDecision: ...


class CourseGraph:
    def __init__(self, nodes: list[Node], gates: dict[str, Gate] | None = None) -> None:
        self.nodes = nodes
        self.gates = gates or {}
        self._index = {n.name: i for i, n in enumerate(nodes)}
        if len(self._index) != len(nodes):
            raise ValueError("CourseGraph node names must be unique")

    async def execute(self, state: GraphState, *, bus=None) -> GraphState:
        from app.agentcore.events.types import custom, step_finished, step_started

        i = 0
        while i < len(self.nodes):
            node = self.nodes[i]
            if bus is not None:
                await bus.emit(step_started(node.name))
            state = await node.run(state, bus=bus)
            if bus is not None:
                await bus.emit(step_finished(node.name))

            gate = self.gates.get(node.name)
            if gate is not None:
                decision = await gate.evaluate(state, bus=bus)
                if (
                    decision.action == "backtrack"
                    and decision.target in self._index
                    and state.backtrack_budget > 0
                ):
                    state.backtrack_budget -= 1
                    state.feedback[decision.target] = decision.feedback
                    if bus is not None:
                        await bus.emit(custom("backtrack", {
                            "from": node.name,
                            "to": decision.target,
                            "feedback": decision.feedback,
                            "budget_left": state.backtrack_budget,
                        }))
                    logger.info(
                        "CourseGraph backtrack %s → %s (budget left %d)",
                        node.name, decision.target, state.backtrack_budget,
                    )
                    i = self._index[decision.target]
                    continue
            i += 1
        return state
