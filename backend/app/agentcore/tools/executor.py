"""ToolExecutor — run a batch of tool calls with hooks, approval, and policy.

Pulled out of the hand-rolled MentorAgent loop so the same execution semantics
(parallel-or-sequential, before/after hooks, approval gate, permission policy,
uniform error wrapping) serve both the chat agent and orchestration ReAct nodes.

Event emission (TOOL_CALL_RESULT) is optional: pass a ``bus`` and the executor
emits one result event per call. The surrounding loop owns TOOL_CALL_START/
ARGS/END (those are streamed from the model), so they are not emitted here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.agent.tools.base import tool_error
from app.agentcore.events.types import custom, tool_call_result
from app.agentcore.tools.approval import Approval, AutoApprove
from app.agentcore.tools.base import Tool, ToolCall, ToolContext, ToolResult

logger = logging.getLogger(__name__)

__all__ = ["ToolHook", "ToolExecutor"]


@runtime_checkable
class ToolHook(Protocol):
    async def before_tool_call(
        self, call: ToolCall, ctx: ToolContext
    ) -> ToolCall | None:
        """Inspect/rewrite a call; return None to skip it."""
        ...

    async def after_tool_call(
        self, call: ToolCall, result: ToolResult, ctx: ToolContext
    ) -> ToolResult:
        """Inspect/rewrite a result (e.g. strip + collect citations)."""
        ...


class ToolExecutor:
    def __init__(
        self,
        tools: Sequence[Tool],
        *,
        hooks: Sequence[ToolHook] = (),
        approval: Approval | None = None,
        policy=None,  # duck-typed PermissionPolicy (avoid tools→policy cycle)
        parallel: bool = True,
        concurrency: int = 4,
    ) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._hooks = list(hooks)
        self._approval = approval or AutoApprove()
        self._policy = policy
        self._parallel = parallel
        self._sem = asyncio.Semaphore(concurrency)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    @property
    def tool_definitions(self):
        """ToolDefinitions for the LLM tool-use schema (None when empty)."""
        defs = [t.to_tool_definition() for t in self._tools.values()]
        return defs or None

    async def run_all(
        self,
        calls: Sequence[ToolCall],
        ctx: ToolContext,
        *,
        bus=None,
    ) -> list[tuple[str, ToolResult]]:
        if self._parallel and len(calls) > 1:
            results = await asyncio.gather(
                *(self._guarded(c, ctx, bus) for c in calls)
            )
            return list(results)
        return [await self._run_one(c, ctx, bus) for c in calls]

    async def _guarded(self, call, ctx, bus):
        async with self._sem:
            return await self._run_one(call, ctx, bus)

    async def _run_one(
        self, call: ToolCall, ctx: ToolContext, bus
    ) -> tuple[str, ToolResult]:
        result = await self._execute(call, ctx)
        if bus is not None:
            await bus.emit(
                tool_call_result(
                    message_id=bus.new_message_id(),
                    tool_call_id=call.id,
                    content=result.content,
                )
            )
            if result.citations:
                await bus.emit(custom("citations", result.citations))
        return call.id, result

    async def _execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        # Permission policy
        if self._policy is not None:
            allowed = await self._policy.allowed(call, ctx)
            if not allowed:
                return ToolResult(
                    content=tool_error(
                        message=f"Tool {call.name!r} blocked by policy.",
                        reason="policy_denied",
                        suggestion="Pick a different tool or ask the user.",
                    ),
                    is_error=True,
                )

        # Human-in-the-loop approval
        if not await self._approval.check(call, ctx):
            return ToolResult(
                content=tool_error(
                    message=f"Tool {call.name!r} not approved.",
                    reason="approval_denied",
                    suggestion="The user declined this action.",
                ),
                is_error=True,
            )

        # before hooks (may rewrite or skip)
        current = call
        for hook in self._hooks:
            current = await hook.before_tool_call(current, ctx)
            if current is None:
                return ToolResult(content="(skipped by hook)", is_error=False)

        tool = self._tools.get(current.name)
        if tool is None:
            return ToolResult(
                content=tool_error(
                    message=f"No tool named {current.name!r}",
                    reason="unknown_tool",
                    suggestion="Available tools: "
                    + ", ".join(self._tools)
                    + ". Pick one by exact name.",
                ),
                is_error=True,
            )

        try:
            result = await tool.run(ctx, **current.input)
        except Exception as e:  # noqa: BLE001
            logger.error("Tool %r crashed: %s", current.name, e, exc_info=True)
            result = ToolResult(
                content=tool_error(
                    message=f"{current.name} crashed: {e}",
                    reason="tool_exception",
                    suggestion="Backend error, not a wrong call. Try a different "
                    "approach or answer from your own knowledge.",
                ),
                is_error=True,
            )

        # after hooks (may rewrite result, e.g. extract citations)
        for hook in self._hooks:
            result = await hook.after_tool_call(current, result, ctx)
        return result
