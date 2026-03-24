"""Anthropic Messages API provider implementation."""

import anthropic
from collections.abc import AsyncIterator

from app.services.llm.base import (
    ContentBlock,
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    StreamChunk,
    TokenUsage,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.adapters.tool_adapter import (
    anthropic_tool_use_to_blocks,
    tool_result_to_anthropic,
    tools_to_anthropic,
)
from app.services.llm.adapters.stream_adapter import normalize_anthropic_stream


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens_limit: int = 4096,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._max_tokens_limit = max_tokens_limit
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=3,
        )

    def _convert_messages(self, messages: list[UnifiedMessage]) -> tuple[str | None, list[dict]]:
        """Convert unified messages to Anthropic format, extracting system message."""
        system = None
        api_messages = []

        for msg in messages:
            if msg.role == "system":
                system = msg.content if isinstance(msg.content, str) else ""
                continue

            if msg.role == "tool_result":
                api_messages.append(tool_result_to_anthropic(msg))
                continue

            if isinstance(msg.content, str):
                api_messages.append({"role": msg.role, "content": msg.content})
            else:
                # Convert ContentBlocks to Anthropic format
                content_parts = []
                for block in msg.content:
                    if block.type == "text":
                        content_parts.append({"type": "text", "text": block.text or ""})
                    elif block.type == "tool_use":
                        content_parts.append({
                            "type": "tool_use",
                            "id": block.tool_use_id,
                            "name": block.tool_name,
                            "input": block.tool_input or {},
                        })
                api_messages.append({"role": msg.role, "content": content_parts})

        return system, api_messages

    async def chat(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Send a chat request and return the complete response."""
        system, api_messages = self._convert_messages(messages)

        params: dict = {
            "model": self._model,
            "max_tokens": min(max_tokens, self._max_tokens_limit),
            "temperature": temperature,
            "messages": api_messages,
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools_to_anthropic(tools)

        try:
            response = await self._client.messages.create(**params)
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except anthropic.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except anthropic.APIError as e:
            raise LLMProviderError(str(e)) from e

        # Convert response content blocks
        content_blocks = []
        for block in response.content:
            if block.type == "text":
                content_blocks.append(ContentBlock(type="text", text=block.text))
            elif block.type == "tool_use":
                content_blocks.extend(
                    anthropic_tool_use_to_blocks([{
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }])
                )

        usage = None
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

        return LLMResponse(
            content=content_blocks,
            model=response.model,
            usage=usage,
            stop_reason=response.stop_reason,
        )

    async def chat_stream(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Send a chat request and return a streaming response."""
        system, api_messages = self._convert_messages(messages)

        params: dict = {
            "model": self._model,
            "max_tokens": min(max_tokens, self._max_tokens_limit),
            "temperature": temperature,
            "messages": api_messages,
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools_to_anthropic(tools)

        try:
            async with self._client.messages.stream(**params) as stream:
                async for chunk in normalize_anthropic_stream(stream):
                    yield chunk
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except anthropic.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except anthropic.APIError as e:
            raise LLMProviderError(str(e)) from e

    def supports_tool_use(self) -> bool:
        """Whether this provider supports native tool use."""
        return True

    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming."""
        return True

    def model_id(self) -> str:
        """The model identifier for this provider instance."""
        return self._model
