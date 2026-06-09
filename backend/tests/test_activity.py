"""Unit tests for the AG-UI tool-call narration helper (tool_activity)."""

import pytest

from app.agentcore.events.activity import tool_activity


class _CaptureBus:
    """Records emitted events; optionally raises to prove best-effort."""

    def __init__(self, *, boom: bool = False) -> None:
        self.events: list = []
        self._boom = boom

    async def emit(self, event) -> None:
        if self._boom:
            raise RuntimeError("sink down")
        self.events.append(event)


def _types(bus: _CaptureBus) -> list[str]:
    # ag_ui events expose `.type` (an EventType enum); compare by value.
    return [getattr(e.type, "value", str(e.type)) for e in bus.events]


async def test_emits_full_tool_call_span_with_summary():
    bus = _CaptureBus()
    async with tool_activity(bus, "analyze.content", args={"chunks": 3}) as act:
        act.set("5 个概念 · 3 段")

    assert _types(bus) == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_RESULT",
        "TOOL_CALL_END",
    ]
    start = bus.events[0]
    assert start.tool_call_name == "analyze.content"
    # start / args / result share the same tool_call_id (one logical call).
    ids = {e.tool_call_id for e in bus.events}
    assert len(ids) == 1
    assert bus.events[2].content == "5 个概念 · 3 段"


async def test_no_summary_skips_result_but_still_ends():
    bus = _CaptureBus()
    async with tool_activity(bus, "plan.sections"):
        pass
    # No args, no summary → only START then END (no empty RESULT).
    assert _types(bus) == ["TOOL_CALL_START", "TOOL_CALL_END"]


async def test_null_bus_is_a_noop():
    # A None bus must not raise and still yields a usable handle.
    async with tool_activity(None, "extract.pdf") as act:
        act.set("ignored")  # no-op, nothing to emit


async def test_exception_in_body_still_closes_the_span():
    bus = _CaptureBus()
    with pytest.raises(ValueError):
        async with tool_activity(bus, "extract.bilibili", args={"url": "x"}) as act:
            act.set("partial")
            raise ValueError("extractor blew up")
    # The span is closed (END emitted) so the UI spinner stops; the error
    # propagates to the caller (run-level RUN_ERROR handles the failure).
    assert _types(bus)[-1] == "TOOL_CALL_END"
    assert "TOOL_CALL_RESULT" in _types(bus)  # the partial summary was flushed


async def test_emit_failure_never_propagates():
    # A sink that raises on every emit must not break the wrapped work.
    bus = _CaptureBus(boom=True)
    async with tool_activity(bus, "embed.vectors", args={"chunks": 1}) as act:
        act.set("1 块")  # body runs fine despite the broken sink
