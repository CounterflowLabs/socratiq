"""PermissionPolicy — gate which tool calls an agent may execute.

The seam for capability scoping (e.g. a student-facing agent that may read but
not mutate, or per-tenant tool allowlists). Default ``AllowAll`` permits every
call — today's behavior. Consumed (duck-typed) by ``ToolExecutor``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agentcore.tools.base import ToolCall, ToolContext

__all__ = ["PermissionPolicy", "AllowAll"]


@runtime_checkable
class PermissionPolicy(Protocol):
    async def allowed(self, call: ToolCall, ctx: ToolContext) -> bool: ...


class AllowAll:
    """Default: every tool call is permitted."""

    async def allowed(self, call: ToolCall, ctx: ToolContext) -> bool:  # noqa: ARG002
        return True
