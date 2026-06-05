"""AgentLoop — the reusable iterate-call-tools loop.

Generalizes the hand-rolled MentorAgent loop: one iteration streams an assistant
turn via the ``LLMClient`` (which emits AG-UI TEXT_MESSAGE / TOOL_CALL events on
the bus), and if the turn requested tools, executes them via the ``ToolExecutor``
(which emits TOOL_CALL_RESULT), appends assistant + tool_result messages, and
loops — until a turn makes no tool calls or ``max_iterations`` is hit.

The loop emits nothing directly; all events flow from the ``LLMClient`` and
``ToolExecutor`` through the shared ``bus``. The loop only mutates ``AgentState``.
"""

from __future__ import annotations

import logging

from app.agentcore.llm.client import LLMClient
from app.agentcore.memory.base import Memory, PassthroughMemory
from app.agentcore.runtime.state import AgentState, LoopConfig
from app.agentcore.tools.base import ToolContext
from app.agentcore.tools.executor import ToolExecutor
from app.services.llm.base import ContentBlock, UnifiedMessage

logger = logging.getLogger(__name__)

__all__ = ["AgentLoop"]


class AgentLoop:
    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolExecutor,
        tool_ctx: ToolContext,
        config: LoopConfig | None = None,
        memory: Memory | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._tool_ctx = tool_ctx
        self._config = config or LoopConfig()
        self._memory = memory or PassthroughMemory()

    async def run(self, state: AgentState, *, bus) -> None:
        cfg = self._config
        tool_defs = self._tools.tool_definitions
        for i in range(cfg.max_iterations):
            state.iteration = i + 1
            if self._tool_ctx.cancellation is not None:
                await self._tool_ctx.cancellation.raise_if_cancelled()

            send = await self._memory.prepare(state.messages)
            turn = await self._llm.stream(
                send,
                tools=tool_defs,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                bus=bus,
            )

            if not turn.tool_calls:
                return  # natural completion

            # Record the assistant turn (text + tool_use blocks), preserving
            # reasoning_content so the provider sees it on the next iteration.
            blocks: list[ContentBlock] = []
            if turn.text:
                blocks.append(ContentBlock(type="text", text=turn.text))
            for tc in turn.tool_calls:
                blocks.append(
                    ContentBlock(
                        type="tool_use",
                        tool_use_id=tc.id,
                        tool_name=tc.name,
                        tool_input=tc.input,
                    )
                )
            state.messages.append(
                UnifiedMessage(
                    role="assistant",
                    content=blocks,
                    reasoning_content=turn.reasoning or None,
                )
            )

            # Execute tools (emits TOOL_CALL_RESULT) and thread results back.
            results = await self._tools.run_all(turn.tool_calls, self._tool_ctx, bus=bus)
            for tool_id, result in results:
                state.messages.append(
                    UnifiedMessage(
                        role="tool_result",
                        content=[
                            ContentBlock(
                                type="tool_result",
                                tool_use_id=tool_id,
                                tool_result_content=result.content,
                                is_error=result.is_error,
                            )
                        ],
                    )
                )
                if cfg.stop_on_tool_error and result.is_error:
                    logger.info("AgentLoop stopping early on tool error")
                    return

            # ReAct termination: a designated tool (e.g. ``finish``) ends the loop.
            if cfg.stop_tools and any(tc.name in cfg.stop_tools for tc in turn.tool_calls):
                return
        else:
            logger.info("AgentLoop hit max_iterations=%d", cfg.max_iterations)
