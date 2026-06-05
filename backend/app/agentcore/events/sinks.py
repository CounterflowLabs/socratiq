"""EventSink implementations for the AG-UI event stream.

A sink is one destination for run events:

  * ``SSEEventSink``       — buffers encoded SSE frames for a FastAPI
                             ``StreamingResponse`` (the live browser client).
  * ``RedisEventSink``     — appends events to a per-run Redis Stream so an ARQ
                             worker can publish progress that a separate web
                             process re-streams over SSE (cross-process).
  * ``TracerEventSink``    — forwards events to the existing ``Tracer`` so the
                             structured ``agent.trace`` log keeps working.
  * ``CheckpointEventSink``— buffers events for replay/resume (Phase-0 default
                             is in-memory; a durable store lands with storage/).

All sinks expose ``async emit(event)``; optional ``async aclose()`` flushes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ag_ui.encoder import EventEncoder

from app.agentcore.events.types import AGUIEvent

logger = logging.getLogger(__name__)

# Shared, stateless encoder (encode() takes the event each call).
_ENCODER = EventEncoder()

# Sentinel pushed onto an SSE queue to signal end-of-stream.
_SSE_DONE = object()


@runtime_checkable
class EventSink(Protocol):
    """One destination for AG-UI events."""

    async def emit(self, event: AGUIEvent) -> None: ...


class QueueEventSink:
    """Buffers raw event objects for an in-process consumer (e.g. AgentRunner).

    Unlike ``SSEEventSink`` (which yields encoded SSE strings), this yields the
    AG-UI event objects themselves, so the runner can hand them to a live
    generator while ``model_dump``/encoding happens at the HTTP boundary.
    """

    def __init__(self, *, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def emit(self, event: AGUIEvent) -> None:
        await self._queue.put(event)

    async def aclose(self) -> None:
        await self._queue.put(_SSE_DONE)

    async def stream(self) -> AsyncIterator[AGUIEvent]:
        while True:
            item = await self._queue.get()
            if item is _SSE_DONE:
                return
            yield item


class SSEEventSink:
    """Buffers encoded SSE frames for a single streaming HTTP response.

    Usage in a FastAPI route::

        sink = SSEEventSink()
        bus = EventBus.new(sinks=[sink])
        # ... drive the run, then ...
        return StreamingResponse(sink.stream(), media_type="text/event-stream")
    """

    def __init__(self, *, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def emit(self, event: AGUIEvent) -> None:
        await self._queue.put(_ENCODER.encode(event))

    async def aclose(self) -> None:
        await self._queue.put(_SSE_DONE)

    async def stream(self) -> AsyncIterator[str]:
        """Yield encoded SSE frames until ``aclose`` is called."""
        while True:
            item = await self._queue.get()
            if item is _SSE_DONE:
                return
            yield item


class RedisEventSink:
    """Append events to a per-run Redis Stream (cross-process transport).

    ARQ worker tasks publish here; the web process subscribes via
    :meth:`subscribe` and re-streams to the browser. Streams (not pub/sub) give
    durability + replay so a reconnecting client can resume from the last id.
    """

    STREAM_PREFIX = "agui:run:"

    def __init__(
        self,
        redis,  # redis.asyncio.Redis
        run_id: str,
        *,
        maxlen: int = 10_000,
    ) -> None:
        self._redis = redis
        self._key = f"{self.STREAM_PREFIX}{run_id}"
        self._maxlen = maxlen

    async def emit(self, event: AGUIEvent) -> None:
        # Store the JSON body (without the SSE "data: " framing) so the
        # subscriber can re-frame for its own transport.
        body = event.model_dump_json(by_alias=True, exclude_none=True)
        await self._redis.xadd(
            self._key, {"e": body}, maxlen=self._maxlen, approximate=True
        )

    async def aclose(self) -> None:
        # Marker so subscribers know the run ended.
        await self._redis.xadd(self._key, {"done": "1"}, maxlen=self._maxlen)

    @classmethod
    async def subscribe(
        cls,
        redis,
        run_id: str,
        *,
        last_id: str = "0",
        block_ms: int = 15_000,
    ) -> AsyncIterator[str]:
        """Yield raw event-JSON strings for ``run_id`` until the done marker.

        ``last_id="0"`` replays from the start (reconnect-safe); pass the last
        seen stream id to resume.
        """
        key = f"{cls.STREAM_PREFIX}{run_id}"
        cursor = last_id
        while True:
            resp = await redis.xread({key: cursor}, count=100, block=block_ms)
            if not resp:
                continue  # block timeout — keep waiting
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    cursor = entry_id
                    if b"done" in fields or "done" in fields:
                        return
                    body = fields.get(b"e") or fields.get("e")
                    if body is None:
                        continue
                    yield body.decode() if isinstance(body, bytes) else body


class TracerEventSink:
    """Forward events to the existing ``Tracer`` (keeps ``agent.trace`` logs)."""

    def __init__(self, tracer=None) -> None:
        if tracer is None:
            from app.services.llm.runtime import get_default_tracer

            tracer = get_default_tracer()
        self._tracer = tracer

    async def emit(self, event: AGUIEvent) -> None:
        fields = event.model_dump(by_alias=False, exclude_none=True)
        event_name = str(fields.pop("type", type(event).__name__))
        self._tracer.emit(event_name, **fields)


class CheckpointEventSink:
    """Buffer events for replay/resume.

    Phase-0 default keeps an in-memory list; a durable ``CheckpointStore``
    (storage/) can be injected later via ``store`` (any object exposing
    ``async append(run_id, json_str)``).
    """

    def __init__(self, run_id: str, *, store=None) -> None:
        self._run_id = run_id
        self._store = store
        self.events: list[str] = []  # in-memory fallback / inspection

    async def emit(self, event: AGUIEvent) -> None:
        body = event.model_dump_json(by_alias=True, exclude_none=True)
        self.events.append(body)
        if self._store is not None:
            await self._store.append(self._run_id, body)
