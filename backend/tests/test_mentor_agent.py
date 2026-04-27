"""Tests for MentorAgent tool-loop message handling."""

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

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(messages.copy())
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
async def test_tool_loop_preserves_reasoning_content_for_same_turn():
    provider = FakeProvider()
    agent = MentorAgent(
        model_router=FakeRouter(provider),
        db=AsyncMock(),
        user_id=uuid.uuid4(),
        tools=[FakeTool()],
    )

    with patch("app.agent.mentor.load_profile", AsyncMock(return_value=StudentProfile())):
        chunks = [
            chunk
            async for chunk in agent.process(
                user_message="question",
                conversation_history=[],
            )
        ]

    assert [chunk.type for chunk in chunks] == ["message_end", "message_end"]
    second_call_messages = provider.calls[1]
    assistant_message = next(
        message for message in second_call_messages if message.role == "assistant"
    )
    assert assistant_message.reasoning_content == "Need to call lookup."
