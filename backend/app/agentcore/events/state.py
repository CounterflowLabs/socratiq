"""StateProjector — emit task progress as AG-UI STATE_SNAPSHOT / STATE_DELTA.

Replaces the ad-hoc ``section_progress_callback`` payload. A projector holds
the authoritative state object for a run, emits one full ``STATE_SNAPSHOT`` up
front, then ``STATE_DELTA`` (RFC 6902 JSON Patch) for each incremental change.
It applies every patch to its own copy too, so the kept state stays current —
a reconnecting client can be re-sent the latest snapshot.

No external JSON-Patch dependency: a small RFC 6901 / 6902 implementation
covers the ops we emit (add / replace / remove / move).
"""

from __future__ import annotations

import copy
from typing import Any

from app.agentcore.events.bus import EventBus
from app.agentcore.events.types import state_delta, state_snapshot


class StateProjector:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._state: Any = None

    @property
    def current(self) -> Any:
        return self._state

    async def snapshot(self, state: Any) -> None:
        """Set the full state and emit STATE_SNAPSHOT."""
        self._state = copy.deepcopy(state)
        await self._bus.emit(state_snapshot(copy.deepcopy(self._state)))

    async def patch(self, ops: list[dict]) -> None:
        """Apply RFC 6902 ops to the kept state and emit STATE_DELTA."""
        self._state = _apply_ops(self._state, ops)
        await self._bus.emit(state_delta(ops))

    async def replace(self, path: str, value: Any) -> None:
        """Convenience: a single ``replace`` op at ``path`` (JSON Pointer)."""
        await self.patch([{"op": "replace", "path": path, "value": value}])


# --- minimal RFC 6901 / 6902 ----------------------------------------------

def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _split_pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError(f"invalid JSON Pointer: {path!r}")
    return [_unescape(t) for t in path.split("/")[1:]]


def _resolve_parent(doc: Any, tokens: list[str]) -> tuple[Any, str | int]:
    """Return (container, key) for the final token, navigating prior tokens."""
    cur = doc
    for tok in tokens[:-1]:
        if isinstance(cur, list):
            cur = cur[int(tok)]
        else:
            cur = cur[tok]
    last = tokens[-1]
    if isinstance(cur, list):
        return cur, (len(cur) if last == "-" else int(last))
    return cur, last


def _apply_ops(doc: Any, ops: list[dict]) -> Any:
    """Apply a sequence of JSON Patch ops, returning the new document."""
    doc = copy.deepcopy(doc)
    for op in ops:
        kind = op["op"]
        tokens = _split_pointer(op["path"])
        if not tokens:  # whole-document replace
            if kind in ("replace", "add"):
                doc = copy.deepcopy(op["value"])
                continue
            raise ValueError(f"op {kind!r} not supported on root path")
        container, key = _resolve_parent(doc, tokens)
        if kind in ("add", "replace"):
            value = copy.deepcopy(op["value"])
            if isinstance(container, list) and kind == "add":
                container.insert(key if key != len(container) else len(container), value)
            else:
                container[key] = value
        elif kind == "remove":
            del container[key]
        elif kind == "move":
            from_tokens = _split_pointer(op["from"])
            src_container, src_key = _resolve_parent(doc, from_tokens)
            moved = src_container[src_key]
            del src_container[src_key]
            if isinstance(container, list):
                container.insert(key, moved)
            else:
                container[key] = moved
        else:
            raise ValueError(f"unsupported JSON Patch op: {kind!r}")
    return doc
