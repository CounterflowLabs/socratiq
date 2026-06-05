"""AG-UI event builders — the single seam between Socratiq and the
``ag-ui-protocol`` SDK.

Everything in agentcore/orchestration constructs events through these factory
functions instead of importing ``ag_ui.core`` directly. The SDK is pinned and
0.x; concentrating its surface here means a breaking SDK change touches one
file. Field names below mirror the SDK (snake_case: ``thread_id``, ``run_id``,
``message_id``, ``tool_call_id`` …) and are serialized to camelCase on the wire
by ``ag_ui.encoder.EventEncoder``.
"""

from __future__ import annotations

from typing import Any, Literal

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

# Public alias used for typing throughout agentcore. Any concrete event built
# below is an instance of BaseEvent.
AGUIEvent = BaseEvent

AssistantRole = Literal["developer", "system", "assistant", "user"]

__all__ = [
    "AGUIEvent",
    "EventType",
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


# --- lifecycle -------------------------------------------------------------

def run_started(
    *, thread_id: str, run_id: str, parent_run_id: str | None = None
) -> RunStartedEvent:
    return RunStartedEvent(
        thread_id=thread_id, run_id=run_id, parent_run_id=parent_run_id
    )


def run_finished(
    *, thread_id: str, run_id: str, result: Any | None = None
) -> RunFinishedEvent:
    return RunFinishedEvent(thread_id=thread_id, run_id=run_id, result=result)


def run_error(*, message: str, code: str | None = None) -> RunErrorEvent:
    return RunErrorEvent(message=message, code=code)


def step_started(name: str) -> StepStartedEvent:
    return StepStartedEvent(step_name=name)


def step_finished(name: str) -> StepFinishedEvent:
    return StepFinishedEvent(step_name=name)


# --- assistant text --------------------------------------------------------

def text_message_start(
    message_id: str, *, role: AssistantRole = "assistant"
) -> TextMessageStartEvent:
    return TextMessageStartEvent(message_id=message_id, role=role)


def text_message_content(message_id: str, delta: str) -> TextMessageContentEvent:
    # SDK requires a non-empty delta; callers must guard empty strings.
    return TextMessageContentEvent(message_id=message_id, delta=delta)


def text_message_end(message_id: str) -> TextMessageEndEvent:
    return TextMessageEndEvent(message_id=message_id)


# --- reasoning -------------------------------------------------------------

def reasoning_start(message_id: str) -> ReasoningMessageStartEvent:
    return ReasoningMessageStartEvent(message_id=message_id, role="reasoning")


def reasoning_content(message_id: str, delta: str) -> ReasoningMessageContentEvent:
    return ReasoningMessageContentEvent(message_id=message_id, delta=delta)


def reasoning_end(message_id: str) -> ReasoningMessageEndEvent:
    return ReasoningMessageEndEvent(message_id=message_id)


# --- tool calls ------------------------------------------------------------

def tool_call_start(
    tool_call_id: str, name: str, *, parent_message_id: str | None = None
) -> ToolCallStartEvent:
    return ToolCallStartEvent(
        tool_call_id=tool_call_id,
        tool_call_name=name,
        parent_message_id=parent_message_id,
    )


def tool_call_args(tool_call_id: str, delta: str) -> ToolCallArgsEvent:
    return ToolCallArgsEvent(tool_call_id=tool_call_id, delta=delta)


def tool_call_end(tool_call_id: str) -> ToolCallEndEvent:
    return ToolCallEndEvent(tool_call_id=tool_call_id)


def tool_call_result(
    *, message_id: str, tool_call_id: str, content: str
) -> ToolCallResultEvent:
    return ToolCallResultEvent(
        message_id=message_id,
        tool_call_id=tool_call_id,
        content=content,
        role="tool",
    )


# --- state (task progress) -------------------------------------------------

def state_snapshot(snapshot: Any) -> StateSnapshotEvent:
    return StateSnapshotEvent(snapshot=snapshot)


def state_delta(ops: list[dict]) -> StateDeltaEvent:
    """RFC 6902 JSON Patch operations describing an incremental state change."""
    return StateDeltaEvent(delta=ops)


# --- escape hatch ----------------------------------------------------------

def custom(name: str, value: Any) -> CustomEvent:
    """Non-standard signals (critic_verdict / replan / backtrack / citations)."""
    return CustomEvent(name=name, value=value)
