"""ReActNode — a judgment node: a bounded agent loop that ends with ``finish``.

Used for the "few nodes that actually need intelligence" in the otherwise
deterministic pipeline — e.g. "is this chapter boundary right?" or "are the
knowledge points sufficient?". The node gives the model a small set of
inspection tools plus a ``finish(decision, reason)`` tool; calling ``finish``
terminates the loop (via ``LoopConfig.stop_tools``). Bounded by
``max_iterations`` and a token budget upstream, so ReAct churn can't run away.

The chosen decision is written to ``state.data[result_key]`` for a downstream
gate / node to act on (e.g. re-cut sections on ``"recut"``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence

from app.agentcore.llm.client import LLMClient
from app.agentcore.runtime.loop import AgentLoop
from app.agentcore.runtime.state import AgentState, LoopConfig
from app.agentcore.tools.base import Tool, ToolContext, ToolDefinition, ToolResult
from app.agentcore.tools.executor import ToolExecutor
from app.services.llm.base import UnifiedMessage
from app.services.orchestration.graph import GraphState

logger = logging.getLogger(__name__)

__all__ = ["FinishTool", "ReActNode"]


class FinishTool:
    """Captures the judgment decision and (via stop_tools) ends the loop."""

    def __init__(self, decisions: Sequence[str]) -> None:
        self._decisions = list(decisions)
        self.decision: str | None = None
        self.reason: str = ""

    name = "finish"

    @property
    def description(self) -> str:
        return (
            "Record your final decision and stop. Call this exactly once when "
            f"you have decided. Allowed decisions: {', '.join(self._decisions)}."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": self._decisions},
                "reason": {"type": "string", "description": "Brief justification."},
            },
            "required": ["decision"],
        }

    def to_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )

    async def run(self, ctx: ToolContext, **params) -> ToolResult:  # noqa: ARG002
        decision = params.get("decision")
        if decision in self._decisions:
            self.decision = decision
        self.reason = params.get("reason", "") or ""
        return ToolResult(content="decision recorded")


class ReActNode:
    def __init__(
        self,
        *,
        name: str,
        llm: LLMClient,
        system_prompt: str,
        context_builder: Callable[[GraphState], str],
        inspect_tools: Sequence[Tool] = (),
        decisions: Sequence[str] = ("accept", "revise"),
        default_decision: str = "accept",
        max_iterations: int = 6,
        result_key: str | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.name = name
        self._llm = llm
        self._system_prompt = system_prompt
        self._context_builder = context_builder
        self._inspect_tools = list(inspect_tools)
        self._decisions = list(decisions)
        self._default = default_decision
        self._max_iterations = max_iterations
        self._result_key = result_key or f"{name}.decision"
        self._temperature = temperature

    async def run(self, state: GraphState, *, bus=None) -> GraphState:
        finish = FinishTool(self._decisions)
        executor = ToolExecutor(
            [*self._inspect_tools, finish], parallel=False
        )
        tool_ctx = ToolContext(extras={"state": state})
        loop = AgentLoop(
            llm=self._llm,
            tools=executor,
            tool_ctx=tool_ctx,
            config=LoopConfig(
                max_iterations=self._max_iterations,
                temperature=self._temperature,
                stop_tools=frozenset({"finish"}),
            ),
        )
        run_id = f"react_{self.name}_{uuid.uuid4().hex[:8]}"
        agent_state = AgentState(
            thread_id=run_id,
            run_id=run_id,
            messages=[
                UnifiedMessage(role="system", content=self._system_prompt),
                UnifiedMessage(role="user", content=self._context_builder(state)),
            ],
        )
        await loop.run(agent_state, bus=bus)

        decision = finish.decision or self._default
        if finish.decision is None:
            logger.info(
                "ReActNode %s did not call finish; defaulting to %r",
                self.name, self._default,
            )
        state.data[self._result_key] = {"decision": decision, "reason": finish.reason}
        return state
