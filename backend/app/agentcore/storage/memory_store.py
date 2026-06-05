"""In-memory default storage implementations.

Process-local, non-durable — fine for tests, single-process dev, and as the
fallback before the Redis/DB-backed stores land. Each satisfies the matching
Protocol in ``storage.base``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.llm.base import UnifiedMessage

__all__ = [
    "InMemoryMessageStore",
    "InMemoryStateStore",
    "InMemoryCheckpointStore",
]


class InMemoryMessageStore:
    def __init__(self) -> None:
        self._threads: dict[str, list[UnifiedMessage]] = defaultdict(list)

    async def load(self, thread_id: str, *, limit: int = 50) -> list[UnifiedMessage]:
        return list(self._threads[thread_id])[-limit:]

    async def append(self, thread_id: str, message: UnifiedMessage) -> None:
        self._threads[thread_id].append(message)


class InMemoryStateStore:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    async def get(self, run_id: str) -> Any | None:
        return self._state.get(run_id)

    async def set(self, run_id: str, state: Any) -> None:
        self._state[run_id] = state


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, dict] = {}
        self._events: dict[str, list[str]] = defaultdict(list)

    async def save(self, run_id: str, checkpoint: dict) -> None:
        self._checkpoints[run_id] = checkpoint

    async def load(self, run_id: str) -> dict | None:
        return self._checkpoints.get(run_id)

    async def append(self, run_id: str, event_json: str) -> None:
        self._events[run_id].append(event_json)

    def events(self, run_id: str) -> list[str]:
        return list(self._events[run_id])
