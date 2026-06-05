"""Storage interfaces for agentcore.

  * ``MessageStore``    — conversation history persistence. Phase-1 binds this
    to the existing ``Conversation``/``Message`` tables via ``DBMessageStore``;
    the in-memory default lives in ``memory_store``.
  * ``StateStore``      — last-known run state (for reconnect / snapshot).
  * ``CheckpointStore`` — durable run checkpoints + event log for replay/resume.

All async so a Redis/Postgres-backed implementation slots in without API
changes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.services.llm.base import UnifiedMessage

__all__ = ["MessageStore", "StateStore", "CheckpointStore"]


@runtime_checkable
class MessageStore(Protocol):
    async def load(self, thread_id: str, *, limit: int = 50) -> list[UnifiedMessage]: ...
    async def append(self, thread_id: str, message: UnifiedMessage) -> None: ...


@runtime_checkable
class StateStore(Protocol):
    async def get(self, run_id: str) -> Any | None: ...
    async def set(self, run_id: str, state: Any) -> None: ...


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, run_id: str, checkpoint: dict) -> None: ...
    async def load(self, run_id: str) -> dict | None: ...
    async def append(self, run_id: str, event_json: str) -> None: ...
