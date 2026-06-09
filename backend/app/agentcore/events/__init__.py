"""agentcore.events — AG-UI event standard for chat + task management.

Public surface: build events via the ``types`` factory functions, fan them out
through an :class:`EventBus` to one or more :class:`EventSink`s, and project
long-running task progress via :class:`StateProjector`.
"""

from app.agentcore.events.activity import ActivityHandle, tool_activity
from app.agentcore.events.bus import EventBus
from app.agentcore.events.sinks import (
    CheckpointEventSink,
    EventSink,
    QueueEventSink,
    RedisEventSink,
    SSEEventSink,
    TracerEventSink,
)
from app.agentcore.events.state import StateProjector
from app.agentcore.events.types import (
    AGUIEvent,
    EventType,
    custom,
    reasoning_content,
    reasoning_end,
    reasoning_start,
    run_error,
    run_finished,
    run_started,
    state_delta,
    state_snapshot,
    step_finished,
    step_started,
    text_message_content,
    text_message_end,
    text_message_start,
    tool_call_args,
    tool_call_end,
    tool_call_result,
    tool_call_start,
)

__all__ = [
    "AGUIEvent",
    "EventType",
    "EventBus",
    "EventSink",
    "QueueEventSink",
    "SSEEventSink",
    "RedisEventSink",
    "TracerEventSink",
    "CheckpointEventSink",
    "StateProjector",
    "ActivityHandle",
    "tool_activity",
    "run_started",
    "run_finished",
    "run_error",
    "step_started",
    "step_finished",
    "text_message_start",
    "text_message_content",
    "text_message_end",
    "reasoning_start",
    "reasoning_content",
    "reasoning_end",
    "tool_call_start",
    "tool_call_args",
    "tool_call_end",
    "tool_call_result",
    "state_snapshot",
    "state_delta",
    "custom",
]
