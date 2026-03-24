"""Tests for Anthropic provider."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.base import (
    ContentBlock,
    LLMAuthError,
    LLMRateLimitError,
    ToolDefinition,
    UnifiedMessage,
)


@pytest.fixture
def provider():
    return AnthropicProvider(model="claude-sonnet-4-20250514", api_key="test-key")


@pytest.fixture
def sample_messages():
    return [
        UnifiedMessage(role="system", content="You are a helpful tutor."),
        UnifiedMessage(role="user", content="Hello"),
    ]


class TestChat:
    @pytest.mark.asyncio
    async def test_basic_chat(self, provider, sample_messages):
        mock_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Hi there!")],
            model="claude-sonnet-4-20250514",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )
        provider._client.messages.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(sample_messages)
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert result.content[0].text == "Hi there!"
        assert result.usage.input_tokens == 10
        assert result.model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_chat_with_tools(self, provider, sample_messages):
        tools = [
            ToolDefinition(name="search", description="Search", parameters={"type": "object", "properties": {}}),
        ]
        mock_response = SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id="tu_1", name="search", input={"query": "test"}),
            ],
            model="claude-sonnet-4-20250514",
            usage=SimpleNamespace(input_tokens=15, output_tokens=10),
            stop_reason="tool_use",
        )
        provider._client.messages.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(sample_messages, tools=tools)
        assert result.content[0].type == "tool_use"
        assert result.content[0].tool_name == "search"
        assert result.stop_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_system_message_extracted(self, provider, sample_messages):
        mock_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Hi")],
            model="claude-sonnet-4-20250514",
            usage=None,
            stop_reason="end_turn",
        )
        provider._client.messages.create = AsyncMock(return_value=mock_response)

        await provider.chat(sample_messages)
        call_kwargs = provider._client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are a helpful tutor."
        # system message should not be in messages list
        for msg in call_kwargs["messages"]:
            assert msg["role"] != "system"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_rate_limit(self, provider, sample_messages):
        import anthropic
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        )
        with pytest.raises(LLMRateLimitError):
            await provider.chat(sample_messages)

    @pytest.mark.asyncio
    async def test_auth_error(self, provider, sample_messages):
        import anthropic
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        with pytest.raises(LLMAuthError):
            await provider.chat(sample_messages)


class TestProperties:
    def test_supports_tool_use(self, provider):
        assert provider.supports_tool_use() is True

    def test_supports_streaming(self, provider):
        assert provider.supports_streaming() is True

    def test_model_id(self, provider):
        assert provider.model_id() == "claude-sonnet-4-20250514"
