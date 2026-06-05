"""AgentRunner — drive one agent run and stream its AG-UI events.

Wraps an :class:`AgentLoop` with run lifecycle: emits ``RUN_STARTED`` …
``RUN_FINISHED``/``RUN_ERROR`` and fans every event (loop + tool) through an
:class:`EventBus`. ``run()`` is an async generator of AG-UI events for a live
consumer (the chat SSE endpoint); side sinks (tracer, redis, checkpoint) on the
same bus receive the identical stream, so task-management consumers don't need
to drain the generator.

The loop runs as a task so streamed events surface to the consumer as they are
produced; the run task shares the caller's resources (e.g. db session inside a
tool context), so the generator must be driven to completion within that scope.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from app.agentcore.events import types as ev
from app.agentcore.events.bus import EventBus
from app.agentcore.events.sinks import EventSink, QueueEventSink
from app.agentcore.runtime.loop import AgentLoop
from app.agentcore.runtime.state import AgentState
from app.services.llm.base import UnifiedMessage

logger = logging.getLogger(__name__)

__all__ = ["AgentRunner"]

RunEndHook = Callable[[AgentState], Awaitable[None]]


class AgentRunner:
    def __init__(
        self,
        *,
        loop: AgentLoop,
        sinks: Sequence[EventSink] = (),
        thread_id: str | None = None,
        run_id: str | None = None,
        run_end_hooks: Sequence[RunEndHook] = (),
    ) -> None:
        self._loop = loop
        self._extra_sinks = list(sinks)
        self._thread_id = thread_id
        self._run_id = run_id
        self._run_end_hooks = list(run_end_hooks)

    async def run(self, messages: Sequence[UnifiedMessage]) -> AsyncIterator:
        queue = QueueEventSink()
        bus = EventBus.new(
            sinks=[queue, *self._extra_sinks],
            thread_id=self._thread_id,
            run_id=self._run_id,
        )
        state = AgentState(
            thread_id=bus.thread_id, run_id=bus.run_id, messages=list(messages)
        )
        driver = asyncio.create_task(self._drive(state, bus, queue))
        try:
            async for event in queue.stream():
                yield event
        finally:
            # Ensure the run task finishes (or is cancelled on client disconnect)
            # before the caller's resources (db session) go away.
            if not driver.done():
                driver.cancel()
            try:
                await driver
            except asyncio.CancelledError:
                pass

    async def _drive(self, state: AgentState, bus: EventBus, queue: QueueEventSink) -> None:
        await bus.emit(ev.run_started(thread_id=bus.thread_id, run_id=bus.run_id))
        try:
            await self._loop.run(state, bus=bus)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent run failed")
            await bus.emit(ev.run_error(message=str(exc)))
        else:
            await bus.emit(ev.run_finished(thread_id=bus.thread_id, run_id=bus.run_id))
        finally:
            for hook in self._run_end_hooks:
                try:
                    await hook(state)
                except Exception:  # noqa: BLE001
                    logger.warning("run_end hook failed", exc_info=True)
            await queue.aclose()
