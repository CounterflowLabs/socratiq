"""Tests for MentorAgent (now an agentcore consumer emitting AG-UI events)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.mentor import MentorAgent
from app.agent.tools.base import AgentTool
from app.services.llm.base import StreamChunk
from app.services.llm.router import TaskType
from app.services.profile import StudentProfile


class FakeTool(AgentTool):
    @property
    def name(self) -> str:
        return "lookup"

    @property
    def description(self) -> str:
        return "Lookup test data"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(self, **params) -> str:
        return f"result for {params['query']}"


class FakeRouter:
    def __init__(self, provider):
        self.provider = provider

    async def get_provider(self, task_type: TaskType):
        return self.provider


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
            yield StreamChunk(
                type="reasoning_delta",
                reasoning_content="Need to call lookup.",
            )
            yield StreamChunk(
                type="tool_use_start",
                tool_use_id="call_1",
                tool_name="lookup",
            )
            yield StreamChunk(
                type="tool_use_delta",
                tool_input_delta='{"query": "weather"}',
            )
            yield StreamChunk(type="tool_use_end")
            yield StreamChunk(type="message_end")
            return
        yield StreamChunk(type="message_end")


@pytest.mark.asyncio
async def test_tool_loop_emits_agui_and_preserves_reasoning_content():
    provider = FakeProvider()
    agent = MentorAgent(
        model_router=FakeRouter(provider),
        db=AsyncMock(),
        user_id=uuid.uuid4(),
        tools=[FakeTool()],
    )

    with patch("app.agent.mentor.load_profile", AsyncMock(return_value=StudentProfile())):
        events = [
            event
            async for event in agent.process(
                user_message="question",
                conversation_history=[],
            )
        ]

    types = [e.type.value for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert "REASONING_MESSAGE_START" in types
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_RESULT" in types

    # The tool result reached the model, and reasoning_content is preserved on
    # the assistant message sent on the second turn.
    result_ev = next(e for e in events if e.type.value == "TOOL_CALL_RESULT")
    assert result_ev.content == "result for weather"

    assert len(provider.calls) == 2
    second_call_messages = provider.calls[1]
    assistant_message = next(
        message for message in second_call_messages if message.role == "assistant"
    )
    assert assistant_message.reasoning_content == "Need to call lookup."
