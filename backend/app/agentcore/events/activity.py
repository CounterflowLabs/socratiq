"""Narrate a deterministic pipeline sub-step as an AG-UI tool call.

The orchestration layer (ingestion / generation tasks, graph nodes) wraps each
external call or meaningful sub-step in :func:`tool_activity`. This emits the
standard AG-UI ``TOOL_CALL_START`` → (optional ``TOOL_CALL_ARGS``) →
(optional ``TOOL_CALL_RESULT``) → ``TOOL_CALL_END`` sequence so the web SSE
channel can render a live "what's happening now" feed — the *same* wire format
a real model-driven tool call produces, so narrated and (future) genuinely
agentic tool calls share one renderer instead of forking into two display
paths.

No LLM is involved: this is instrumentation around work the pipeline already
does, so the token cost is zero. Best-effort by design — a ``None`` bus is a
no-op, and emit failures never propagate into the pipeline (the work is
authoritative; the live feed is decorative).

Usage::

    async with tool_activity(event_bus, "extract.bilibili", args={"url": url}) as act:
        result = await extractor.extract(url)
        act.set(f"{len(result.chunks)} 段")
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.agentcore.events.types import (
    tool_call_args,
    tool_call_end,
    tool_call_result,
    tool_call_start,
)


class ActivityHandle:
    """Handle yielded by :func:`tool_activity`; lets the wrapped body record a
    short outcome summary that surfaces on the activity feed when the call
    finishes (e.g. ``"字幕 1240 行 · 52m"``)."""

    __slots__ = ("summary",)

    def __init__(self) -> None:
        self.summary: str = ""

    def set(self, summary: str) -> None:
        self.summary = summary


@asynccontextmanager
async def tool_activity(
    bus: Any,
    name: str,
    *,
    args: dict[str, Any] | None = None,
) -> AsyncIterator[ActivityHandle]:
    """Emit a narrated AG-UI tool-call span around a pipeline sub-step.

    Args:
        bus: The run's ``EventBus``; ``None`` makes this a pure no-op so call
            sites need no branching when no run is attached.
        name: Stable technical tag for the call (e.g. ``"analyze.content"``,
            ``"references.search"``). The frontend maps it to a localized
            label; unknown tags render verbatim.
        args: Optional structured arguments shown as call detail (e.g. the
            query or model). Serialized to JSON; keep it small and free of
            secrets / PII.

    Yields:
        An :class:`ActivityHandle` whose ``set()`` records the outcome summary.
    """
    handle = ActivityHandle()
    if bus is None:
        yield handle
        return

    call_id = uuid.uuid4().hex
    msg_id = uuid.uuid4().hex

    async def _safe(coro: Any) -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001 — the feed is best-effort, never fatal
            pass

    await _safe(bus.emit(tool_call_start(call_id, name)))
    if args:
        await _safe(
            bus.emit(tool_call_args(call_id, json.dumps(args, ensure_ascii=False)))
        )
    try:
        yield handle
    finally:
        if handle.summary:
            await _safe(
                bus.emit(
                    tool_call_result(
                        message_id=msg_id,
                        tool_call_id=call_id,
                        content=handle.summary,
                    )
                )
            )
        await _safe(bus.emit(tool_call_end(call_id)))
