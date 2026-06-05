"""EventBus — fan-out of AG-UI events to one or more sinks.

A bus is scoped to a single run (``thread_id`` + ``run_id``). The agent loop
and orchestration nodes push events through ``emit``; the bus forwards each to
every registered sink. Sink failures are isolated and logged — one broken sink
(e.g. a dropped SSE client) must never abort the run or starve the others.

The bus also vends id generators so message/tool-call ids are unique and
monotonically ordered within a run, which downstream consumers rely on to
reassemble streamed text and tool calls.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import uuid
from collections.abc import Sequence

from app.agentcore.events.sinks import EventSink
from app.agentcore.events.types import AGUIEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Per-run fan-out to AG-UI :class:`EventSink`s."""

    def __init__(
        self,
        *,
        thread_id: str,
        run_id: str,
        sinks: Sequence[EventSink] = (),
    ) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._sinks: list[EventSink] = list(sinks)
        self._seq = itertools.count()

    @classmethod
    def new(
        cls,
        *,
        sinks: Sequence[EventSink] = (),
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> "EventBus":
        """Create a bus, generating thread/run ids when not supplied."""
        return cls(
            thread_id=thread_id or f"thr_{uuid.uuid4().hex}",
            run_id=run_id or f"run_{uuid.uuid4().hex}",
            sinks=sinks,
        )

    def add_sink(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    # --- id generation (unique + ordered within a run) ---------------------

    def new_message_id(self) -> str:
        return f"msg_{next(self._seq):06d}_{uuid.uuid4().hex[:8]}"

    def new_tool_call_id(self) -> str:
        return f"tc_{next(self._seq):06d}_{uuid.uuid4().hex[:8]}"

    # --- emission ----------------------------------------------------------

    async def emit(self, event: AGUIEvent) -> None:
        """Forward ``event`` to all sinks concurrently, isolating failures."""
        if not self._sinks:
            return
        results = await asyncio.gather(
            *(self._emit_one(sink, event) for sink in self._sinks),
            return_exceptions=True,
        )
        for sink, res in zip(self._sinks, results):
            if isinstance(res, Exception):
                logger.warning(
                    "EventSink %s failed on %s: %s",
                    type(sink).__name__,
                    getattr(event, "type", "?"),
                    res,
                )

    @staticmethod
    async def _emit_one(sink: EventSink, event: AGUIEvent) -> None:
        await sink.emit(event)

    async def aclose(self) -> None:
        """Close every sink that supports it (flushes SSE/Redis tails)."""
        for sink in self._sinks:
            aclose = getattr(sink, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:  # noqa: BLE001
                    logger.warning("Error closing sink %s", type(sink).__name__)
