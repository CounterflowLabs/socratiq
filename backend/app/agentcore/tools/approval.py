"""Approval — human-in-the-loop gate for tool calls.

AG-UI supports human-in-the-loop flows; this is the seam for them. The default
``AutoApprove`` lets every call through (today's behavior). A real
implementation would emit an approval-request event and await a resolution
before returning, enabling "agent proposes, user confirms" UX.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agentcore.tools.base import ToolCall, ToolContext

__all__ = ["Approval", "AutoApprove"]


@runtime_checkable
class Approval(Protocol):
    async def check(self, call: ToolCall, ctx: ToolContext) -> bool:
        """Return True to allow the call, False to deny it."""
        ...


class AutoApprove:
    """Default policy: approve everything."""

    async def check(self, call: ToolCall, ctx: ToolContext) -> bool:  # noqa: ARG002
        return True
