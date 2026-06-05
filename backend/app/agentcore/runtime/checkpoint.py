"""Checkpointer — snapshot/restore AgentState for resumable runs.

Interface only this phase; the default ``NoopCheckpointer`` does nothing.
Durable resume (Redis-backed) is deferred per the approved plan, but the seam
exists so the loop can call ``await checkpointer.save(state)`` unconditionally.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agentcore.runtime.state import AgentState

__all__ = ["Checkpointer", "NoopCheckpointer"]


@runtime_checkable
class Checkpointer(Protocol):
    async def save(self, state: AgentState) -> None: ...
    async def load(self, run_id: str) -> AgentState | None: ...


class NoopCheckpointer:
    """Default: checkpointing disabled."""

    async def save(self, state: AgentState) -> None:  # noqa: ARG002
        return None

    async def load(self, run_id: str) -> AgentState | None:  # noqa: ARG002
        return None
