"""Tool abstractions for agentcore.

Reuses the existing ``ToolDefinition`` (``app.services.llm.base``) and the
``tool_error``/``is_tool_error`` helpers (``app.agent.tools.base``) — agentcore
does not redefine the LLM-facing tool schema, it adds the *execution* surface:

  * ``ToolContext`` — per-run dependencies handed to a tool (db session,
    user id, cancellation, an event-emit hook, free-form extras).
  * ``ToolResult``  — structured outcome (content + error flag + citations +
    UI artifacts) instead of a bare string.
  * ``Tool``        — the protocol the executor runs against.
  * ``AgentToolAdapter`` — wraps a legacy ``AgentTool`` (string-returning
    ``execute(**params)``) as a ``Tool``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.agent.tools.base import AgentTool, is_tool_error
from app.services.llm.base import ToolDefinition

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agentcore.runtime.cancellation import CancellationToken

__all__ = [
    "ToolDefinition",
    "ToolContext",
    "ToolResult",
    "ToolCall",
    "Tool",
    "AgentToolAdapter",
    "is_tool_error",
]


@dataclass
class ToolContext:
    """Per-run dependencies passed to a tool's ``run``."""

    db: "AsyncSession | None" = None
    user_id: "uuid.UUID | None" = None
    cancellation: "CancellationToken | None" = None
    emit: "Callable[[Any], Awaitable[None]] | None" = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Structured tool outcome. ``content`` is what the LLM sees."""

    content: str
    is_error: bool = False
    citations: list[dict] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_string(cls, text: str, *, citations: list[dict] | None = None) -> "ToolResult":
        """Build from a legacy string result, detecting the error shape."""
        return cls(
            content=text,
            is_error=is_tool_error(text),
            citations=citations or [],
        )


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    input: dict


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict

    async def run(self, ctx: ToolContext, **params: Any) -> ToolResult: ...

    def to_tool_definition(self) -> ToolDefinition: ...


class AgentToolAdapter:
    """Adapt a legacy ``AgentTool`` (string ``execute``) to the ``Tool`` protocol.

    The legacy tools already hold their own db/user/service deps via ``__init__``,
    so the adapter ignores ``ctx`` for execution and just wraps the string into a
    ``ToolResult``. Citation extraction stays a loop-level hook, not the adapter's
    job.
    """

    def __init__(self, tool: AgentTool) -> None:
        self._tool = tool

    @property
    def name(self) -> str:
        return self._tool.name

    @property
    def description(self) -> str:
        return self._tool.description

    @property
    def parameters(self) -> dict:
        return self._tool.parameters

    def to_tool_definition(self) -> ToolDefinition:
        return self._tool.to_tool_definition()

    async def run(self, ctx: ToolContext, **params: Any) -> ToolResult:  # noqa: ARG002
        text = await self._tool.execute(**params)
        return ToolResult.from_string(text)
