"""Phase-1 core: AgentRunner + AgentLoop + RouterLLMClient.stream end-to-end.

Mirrors the FakeProvider contract from test_mentor_agent: turn 1 streams
reasoning + a tool call, turn 2 streams nothing (loop ends). Asserts the AG-UI
event lifecycle, tool execution, and that reasoning_content is preserved on the
assistant message fed back to the provider next turn.
"""

from __future__ import annotations

import pytest

from app.agentcore.llm.router_client import RouterLLMClient
from app.agentcore.runtime import AgentLoop, AgentRunner
from app.agentcore.tools.base import ToolContext, ToolResult
from app.agentcore.tools.executor import ToolExecutor
from app.services.llm.base import StreamChunk, ToolDefinition, UnifiedMessage
from app.services.llm.router import TaskType


class LookupTool:
    name = "lookup"
    description = "Lookup test data"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def run(self, ctx: ToolContext, **params) -> ToolResult:
        return ToolResult(content=f"result for {params['query']}")

    def to_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=self.description, parameters=self.parameters
        )


class FakeProvider:
    def __init__(self):
        self.calls = []

    def supports_streaming(self) -> bool:
        return True

    def model_id(self) -> str:
        return "fake-model"

    async def chat_stream(self, messages, **kwargs):
        self.calls.append([m.model_copy(deep=True) for m in messages])
        if len(self.calls) == 1:
            yield StreamChunk(type="reasoning_delta", reasoning_content="Need to call lookup.")
            yield StreamChunk(type="tool_use_start", tool_use_id="call_1", tool_name="lookup")
            yield StreamChunk(type="tool_use_delta", tool_input_delta='{"query": "weather"}')
            yield StreamChunk(type="tool_use_end")
            yield StreamChunk(type="message_end")
            return
        yield StreamChunk(type="message_end")


class FakeRouter:
    def __init__(self, provider):
        self.provider = provider

    async def get_provider(self, task_type: TaskType):
        return self.provider


def _types(events) -> list[str]:
    return [e.type.value for e in events]


async def test_runner_drives_tool_loop_and_emits_agui_lifecycle():
    provider = FakeProvider()
    client = RouterLLMClient(FakeRouter(provider), primary=TaskType.MENTOR_CHAT)
    loop = AgentLoop(
        llm=client,
        tools=ToolExecutor([LookupTool()], parallel=False),
        tool_ctx=ToolContext(),
    )
    runner = AgentRunner(loop=loop)

    events = [
        e async for e in runner.run([UnifiedMessage(role="user", content="question")])
    ]
    types = _types(events)

    # Lifecycle bookends
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    # Turn 1 produced reasoning, a tool call, and a tool result
    assert "REASONING_MESSAGE_START" in types
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_END" in types
    assert "TOOL_CALL_RESULT" in types

    # The tool result event carries the tool output
    result_ev = next(e for e in events if e.type.value == "TOOL_CALL_RESULT")
    assert result_ev.content == "result for weather"
    assert result_ev.tool_call_id == "call_1"

    # Two provider turns; the 2nd sees an assistant message with preserved
    # reasoning_content and a tool_result message.
    assert len(provider.calls) == 2
    second = provider.calls[1]
    assistant = next(m for m in second if m.role == "assistant")
    assert assistant.reasoning_content == "Need to call lookup."
    assert any(m.role == "tool_result" for m in second)


async def test_runner_no_tool_calls_finishes_immediately():
    class TextOnly(FakeProvider):
        async def chat_stream(self, messages, **kwargs):
            self.calls.append(messages)
            yield StreamChunk(type="text_delta", text="hello ")
            yield StreamChunk(type="text_delta", text="world")
            yield StreamChunk(type="message_end")

    provider = TextOnly()
    client = RouterLLMClient(FakeRouter(provider), primary=TaskType.MENTOR_CHAT)
    loop = AgentLoop(llm=client, tools=ToolExecutor([]), tool_ctx=ToolContext())
    runner = AgentRunner(loop=loop)

    events = [e async for e in runner.run([UnifiedMessage(role="user", content="hi")])]
    types = _types(events)
    assert types[0] == "RUN_STARTED"
    assert "TEXT_MESSAGE_START" in types
    assert "TEXT_MESSAGE_CONTENT" in types
    assert "TEXT_MESSAGE_END" in types
    assert types[-1] == "RUN_FINISHED"
    # text streamed in two deltas
    deltas = [e.delta for e in events if e.type.value == "TEXT_MESSAGE_CONTENT"]
    assert "".join(deltas) == "hello world"
    assert len(provider.calls) == 1  # no tool loop
