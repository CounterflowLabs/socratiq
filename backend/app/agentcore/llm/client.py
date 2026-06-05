"""LLMClient — the interface the agent loop and generators call.

Two methods, deliberately distinct shapes:

  * ``complete()`` — non-streaming, optional validator + corrective retry.
    Returns a ``CallResult`` (the existing runtime result). This is what the
    one-shot generators (lesson/lab/analyzer/section_planner) use.
  * ``stream()``  — streaming; translates provider ``StreamChunk``s into AG-UI
    events on the bus and returns a ``TurnResult`` for the loop to act on.

The concrete ``RouterLLMClient`` implements both over the existing
``ModelRouter`` + ``AgentRuntime`` + ``chat_stream`` (see ``router_client``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.agentcore.tools.base import ToolCall
from app.services.llm.base import TokenUsage, ToolDefinition, UnifiedMessage

if TYPE_CHECKING:
    from app.services.llm.runtime import CallResult

__all__ = ["TurnResult", "LLMClient"]


@dataclass
class TurnResult:
    """Outcome of one streamed assistant turn."""

    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    provider_used: str = ""
    stop_reason: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        validator=None,
        max_validation_retries: int = 1,
        phase: str = "llm_call",
    ) -> "CallResult": ...

    async def stream(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        bus=None,
        parent_message_id: str | None = None,
    ) -> TurnResult: ...
