"""Tests for OpenAI-compatible provider."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.openai_compat import OpenAICompatProvider
from app.services.llm.base import (
    ContentBlock,
    LLMRateLimitError,
    LLMAuthError,
    ToolDefinition,
    UnifiedMessage,
)


@pytest.fixture
def provider():
    return OpenAICompatProvider(model="gpt-4o-mini", api_key="test-key")


@pytest.fixture
def no_tools_provider():
    return OpenAICompatProvider(
        model="qwen2.5",
        base_url="http://localhost:11434/v1",
        supports_tools=False,
    )


@pytest.fixture
def sample_messages():
    return [
        UnifiedMessage(role="system", content="You are helpful."),
        UnifiedMessage(role="user", content="Hello"),
    ]


class TestChat:
    @pytest.mark.asyncio
    async def test_basic_chat(self, provider, sample_messages):
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Hi!", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            model="gpt-4o-mini",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await provider.chat(sample_messages)
        assert len(result.content) == 1
        assert result.content[0].text == "Hi!"
        assert result.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_chat_with_native_tools(self, provider, sample_messages):
        tools = [
            ToolDefinition(
                name="search",
                description="Search",
                parameters={"type": "object", "properties": {}},
            )
        ]
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="search",
                                    arguments='{"query": "test"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            model="gpt-4o-mini",
            usage=SimpleNamespace(prompt_tokens=15, completion_tokens=10),
        )
        provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await provider.chat(sample_messages, tools=tools)
        assert result.content[0].type == "tool_use"
        assert result.content[0].tool_name == "search"

    @pytest.mark.asyncio
    async def test_assistant_tool_message_preserves_reasoning_content(self, provider):
        messages = [
            UnifiedMessage(role="user", content="How is the weather?"),
            UnifiedMessage(
                role="assistant",
                content=[
                    ContentBlock(
                        type="tool_use",
                        tool_use_id="call_1",
                        tool_name="search",
                        tool_input={"query": "weather"},
                    )
                ],
                reasoning_content="I need to search before answering.",
            ),
            UnifiedMessage(
                role="tool_result",
                content=[
                    ContentBlock(
                        type="tool_result",
                        tool_use_id="call_1",
                        tool_result_content="Sunny",
                    )
                ],
            ),
        ]
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Sunny.", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            model="gpt-4o-mini",
            usage=None,
        )
        provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        await provider.chat(messages)

        request_messages = provider._client.chat.completions.create.call_args.kwargs[
            "messages"
        ]
        assert request_messages[1]["reasoning_content"] == (
            "I need to search before answering."
        )

    @pytest.mark.asyncio
    async def test_prompt_injection_fallback(self, no_tools_provider, sample_messages):
        """When supports_tools=False, tool definitions should be injected into system prompt."""
        tools = [
            ToolDefinition(
                name="search",
                description="Search",
                parameters={"type": "object", "properties": {}},
            )
        ]
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "Let me search.\n"
                            "<tool_call>\n"
                            '{"name": "search", "arguments": {"query": "test"}}\n'
                            "</tool_call>"
                        ),
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            model="qwen2.5",
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=15),
        )
        no_tools_provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await no_tools_provider.chat(sample_messages, tools=tools)
        # Should have extracted tool call from text
        tool_blocks = [b for b in result.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_name == "search"

    @pytest.mark.asyncio
    async def test_custom_base_url(self):
        """Verify base_url is passed to client."""
        p = OpenAICompatProvider(
            model="deepseek-chat",
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
        )
        assert p._client.base_url.host == "api.deepseek.com"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_rate_limit(self, provider, sample_messages):
        import openai as openai_mod

        provider._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            )
        )
        with pytest.raises(LLMRateLimitError):
            await provider.chat(sample_messages)

    @pytest.mark.asyncio
    async def test_auth_error(self, provider, sample_messages):
        import openai as openai_mod

        provider._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.AuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            )
        )
        with pytest.raises(LLMAuthError):
            await provider.chat(sample_messages)


class TestProperties:
    def test_supports_tool_use_true(self, provider):
        assert provider.supports_tool_use() is True

    def test_supports_tool_use_false(self, no_tools_provider):
        assert no_tools_provider.supports_tool_use() is False

    def test_model_id(self, provider):
        assert provider.model_id() == "gpt-4o-mini"
