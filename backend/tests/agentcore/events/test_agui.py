"""Phase-0 gate: AG-UI event layer.

Asserts that everything agentcore emits is a valid ``ag_ui.core`` event, encodes
to well-formed SSE (camelCase), fans out through the bus with sink isolation,
and that StateProjector produces valid RFC 6902 deltas while keeping its state
current.
"""

from __future__ import annotations

import json

import pytest
from ag_ui.core import BaseEvent
from ag_ui.encoder import EventEncoder

from app.agentcore.events import (
    EventBus,
    SSEEventSink,
    StateProjector,
    custom,
    run_started,
    state_delta,
    text_message_content,
    text_message_start,
    tool_call_result,
)
from app.agentcore.events.sinks import RedisEventSink
from app.agentcore.events.state import _apply_ops


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    async def emit(self, event: BaseEvent) -> None:
        self.events.append(event)


class ExplodingSink:
    async def emit(self, event: BaseEvent) -> None:  # noqa: ARG002
        raise RuntimeError("boom")


def test_builders_are_core_events_and_encode_to_sse():
    enc = EventEncoder()
    events = [
        run_started(thread_id="t", run_id="r"),
        text_message_start("m1"),
        text_message_content("m1", "hello"),
        tool_call_result(message_id="m2", tool_call_id="tc1", content="ok"),
        custom("citations", [{"source_id": "s1"}]),
    ]
    for ev in events:
        assert isinstance(ev, BaseEvent)
        frame = enc.encode(ev)
        assert frame.startswith("data: ") and frame.endswith("\n\n")
        payload = json.loads(frame[len("data: ") :].strip())
        assert "type" in payload  # camelCase wire form

    # camelCase serialization of snake_case fields
    rs = json.loads(enc.encode(run_started(thread_id="t", run_id="r"))[6:])
    assert rs["threadId"] == "t" and rs["runId"] == "r"


async def test_bus_fans_out_and_isolates_sink_failures():
    good1, good2 = CapturingSink(), CapturingSink()
    bus = EventBus.new(sinks=[good1, ExplodingSink(), good2])
    await bus.emit(text_message_content("m1", "x"))
    # A failing sink must not starve the others.
    assert len(good1.events) == 1
    assert len(good2.events) == 1


def test_bus_ids_are_unique_and_ordered():
    bus = EventBus.new()
    ids = [bus.new_message_id() for _ in range(3)] + [bus.new_tool_call_id()]
    assert len(set(ids)) == 4  # unique
    # sequence prefix is monotonic
    seqs = [int(i.split("_")[1]) for i in ids]
    assert seqs == sorted(seqs)


async def test_sse_sink_streams_and_closes():
    sink = SSEEventSink()
    bus = EventBus.new(sinks=[sink])
    await bus.emit(run_started(thread_id="t", run_id="r"))
    await bus.emit(text_message_content("m1", "hi"))
    await sink.aclose()
    frames = [frame async for frame in sink.stream()]
    assert len(frames) == 2
    assert all(f.startswith("data: ") for f in frames)


async def test_state_projector_snapshot_then_delta_keeps_state_current():
    sink = CapturingSink()
    bus = EventBus.new(sinks=[sink])
    proj = StateProjector(bus)
    await proj.snapshot(
        {"total": 2, "completed": 0, "items": [{"status": "pending"}, {"status": "pending"}]}
    )
    await proj.replace("/items/0/status", "success")
    await proj.patch([{"op": "replace", "path": "/completed", "value": 1}])

    assert sink.events[0].type.value == "STATE_SNAPSHOT"
    assert sink.events[1].type.value == "STATE_DELTA"
    # kept state reflects applied patches (reconnect-safe)
    assert proj.current["items"][0]["status"] == "success"
    assert proj.current["completed"] == 1


def test_apply_ops_supports_add_remove_move():
    doc = {"a": [1, 2], "b": {"x": 1}}
    out = _apply_ops(
        doc,
        [
            {"op": "add", "path": "/a/-", "value": 3},
            {"op": "remove", "path": "/b/x"},
            {"op": "replace", "path": "/a/0", "value": 9},
        ],
    )
    assert out == {"a": [9, 2, 3], "b": {}}
    assert doc == {"a": [1, 2], "b": {"x": 1}}  # input untouched


async def test_redis_event_sink_roundtrip():
    fakeredis = pytest.importorskip("fakeredis")
    redis = fakeredis.aioredis.FakeRedis()
    run_id = "run_test"
    sink = RedisEventSink(redis, run_id)
    await sink.emit(run_started(thread_id="t", run_id=run_id))
    await sink.emit(text_message_content("m1", "hi"))
    await sink.aclose()  # done marker

    got = [body async for body in RedisEventSink.subscribe(redis, run_id, block_ms=50)]
    assert len(got) == 2
    assert json.loads(got[0])["type"] == "RUN_STARTED"
    assert json.loads(got[1])["delta"] == "hi"
    await redis.aclose()
