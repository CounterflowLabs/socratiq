"""OpenAI-compatible provider implementation.

Covers: OpenAI, DeepSeek, Qwen, Ollama, and any OpenAI API-compatible endpoint.
"""

import json
import re
from collections.abc import AsyncIterator

import openai

from app.services.llm.base import (
    ContentBlock,
    EmbeddingProvider,
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
    openai_tool_calls_to_blocks,
    parse_prompt_tool_calls,
    tool_result_to_openai,
    tools_to_openai,
    tools_to_prompt,
)
from app.services.llm.adapters.stream_adapter import normalize_openai_stream


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible API provider."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        supports_tools: bool = True,
        supports_stream: bool = True,
        max_tokens_limit: int = 4096,
        timeout: float = 300.0,
    ) -> None:
        self._model = model
        self._supports_tools = supports_tools
        self._supports_stream = supports_stream
        self._max_tokens_limit = max_tokens_limit
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "not-needed",  # local models may not need a key
            base_url=base_url,
            timeout=timeout,
            max_retries=3,
        )

    def _convert_messages(
        self,
        messages: list[UnifiedMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> list[dict]:
        """Convert unified messages to OpenAI format.

        If tools are provided but native tool use is not supported,
        inject tool definitions into the system prompt.
        """
        api_messages: list[dict] = []
        inject_tools_prompt = bool(tools and not self._supports_tools)

        for msg in messages:
            if msg.role == "system":
                content = msg.content if isinstance(msg.content, str) else ""
                if inject_tools_prompt:
                    content = content + "\n\n" + tools_to_prompt(tools)
                api_messages.append({"role": "system", "content": content})
                continue

            if msg.role == "tool_result":
                api_messages.extend(tool_result_to_openai(msg))
                continue

            if isinstance(msg.content, str):
                api_messages.append({"role": msg.role, "content": msg.content})
            else:
                # For assistant messages with tool_use blocks, convert to OpenAI format
                text_parts: list[str] = []
                tool_calls: list[dict] = []
                for block in msg.content:
                    if block.type == "text" and block.text:
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "id": block.tool_use_id,
                            "type": "function",
                            "function": {
                                "name": block.tool_name,
                                "arguments": json.dumps(block.tool_input or {}),
                            },
                        })

                msg_dict: dict = {"role": msg.role}
                msg_dict["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                api_messages.append(msg_dict)

        # If no system message exists but we need to inject tools
        if inject_tools_prompt and not any(
            m.get("role") == "system" for m in api_messages
        ):
            api_messages.insert(
                0, {"role": "system", "content": tools_to_prompt(tools)}
            )

        return api_messages

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
        api_messages = self._convert_messages(messages, tools)

        params: dict = {
            "model": self._model,
            "max_tokens": min(max_tokens, self._max_tokens_limit),
            "temperature": temperature,
            "messages": api_messages,
        }
        if tools and self._supports_tools:
            params["tools"] = tools_to_openai(tools)

        import logging
        _logger = logging.getLogger(__name__)
        input_chars = sum(len(m.get("content", "")) if isinstance(m.get("content"), str) else 0 for m in api_messages)
        _logger.info(f"LLM request: model={self._model} messages={len(api_messages)} input_chars={input_chars} max_tokens={params.get('max_tokens')} base_url={self._client.base_url}")
        for i, m in enumerate(api_messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str):
                preview = content[:200].replace("\n", "\\n")
            else:
                preview = str(content)[:200]
            _logger.debug(f"  msg[{i}] role={role} len={len(content) if isinstance(content, str) else '?'}: {preview}...")

        try:
            import time as _time
            _t0 = _time.monotonic()
            response = await self._client.chat.completions.create(**params)
            _elapsed = _time.monotonic() - _t0
            _out_text = response.choices[0].message.content or ""
            _logger.info(f"LLM response: model={response.model} elapsed={_elapsed:.1f}s output_chars={len(_out_text)} tokens_in={response.usage.prompt_tokens if response.usage else '?'} tokens_out={response.usage.completion_tokens if response.usage else '?'}")
        except openai.RateLimitError as e:
            _logger.error(f"LLM rate limit: {e}")
            raise LLMRateLimitError(str(e)) from e
        except openai.AuthenticationError as e:
            _logger.error(f"LLM auth error: {e}")
            raise LLMAuthError(str(e)) from e
        except openai.APITimeoutError as e:
            _logger.error(f"LLM timeout after input_chars={input_chars}: {e}")
            raise LLMTimeoutError(str(e)) from e
        except openai.APIError as e:
            _logger.error(f"LLM API error: {e}")
            raise LLMProviderError(str(e)) from e

        choice = response.choices[0]
        content_blocks: list[ContentBlock] = []

        # Text content
        if choice.message.content:
            # If we used prompt injection, check for tool calls in text
            if tools and not self._supports_tools:
                prompt_tool_calls = parse_prompt_tool_calls(choice.message.content)
                if prompt_tool_calls:
                    # Remove tool_call tags from text for clean output
                    clean_text = re.sub(
                        r"<tool_call>.*?</tool_call>",
                        "",
                        choice.message.content,
                        flags=re.DOTALL,
                    ).strip()
                    if clean_text:
                        content_blocks.append(
                            ContentBlock(type="text", text=clean_text)
                        )
                    content_blocks.extend(prompt_tool_calls)
                else:
                    content_blocks.append(
                        ContentBlock(type="text", text=choice.message.content)
                    )
            else:
                content_blocks.append(
                    ContentBlock(type="text", text=choice.message.content)
                )

        # Native tool calls
        if choice.message.tool_calls:
            content_blocks.extend(
                openai_tool_calls_to_blocks([
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.message.tool_calls
                ])
            )

        usage = None
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )

        return LLMResponse(
            content=content_blocks,
            model=response.model or self._model,
            usage=usage,
            stop_reason=choice.finish_reason,
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
        if not self._supports_stream:
            # Fallback: call non-streaming and yield as single chunks
            response = await self.chat(
                messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            for block in response.content:
                if block.type == "text":
                    yield StreamChunk(type="text_delta", text=block.text)
                elif block.type == "tool_use":
                    yield StreamChunk(
                        type="tool_use_start",
                        tool_use_id=block.tool_use_id,
                        tool_name=block.tool_name,
                    )
                    yield StreamChunk(
                        type="tool_use_delta",
                        tool_input_delta=json.dumps(block.tool_input or {}),
                    )
                    yield StreamChunk(type="tool_use_end")
            yield StreamChunk(type="message_end", usage=response.usage)
            return

        api_messages = self._convert_messages(messages, tools)
        params: dict = {
            "model": self._model,
            "max_tokens": min(max_tokens, self._max_tokens_limit),
            "temperature": temperature,
            "messages": api_messages,
            "stream": True,
        }
        if tools and self._supports_tools:
            params["tools"] = tools_to_openai(tools)

        try:
            raw_stream = await self._client.chat.completions.create(**params)
            async for chunk in normalize_openai_stream(raw_stream):
                yield chunk
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except openai.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.APIError as e:
            raise LLMProviderError(str(e)) from e

    def supports_tool_use(self) -> bool:
        """Whether this provider supports native tool use."""
        return self._supports_tools

    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming."""
        return self._supports_stream

    def model_id(self) -> str:
        """The model identifier for this provider instance."""
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings using the OpenAI embeddings API."""
        import logging, time as _time
        _logger = logging.getLogger(__name__)
        total_chars = sum(len(t) for t in texts)
        _logger.info(f"Embed request: model={self._model} texts={len(texts)} total_chars={total_chars}")
        _t0 = _time.monotonic()
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        _elapsed = _time.monotonic() - _t0
        _logger.info(f"Embed response: model={self._model} elapsed={_elapsed:.1f}s dims={len(response.data[0].embedding) if response.data else '?'}")
        return [item.embedding for item in response.data]


class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding-only provider.

    Inherits from EmbeddingProvider: chat methods raise LLMError,
    test_connectivity uses embed.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._model = model
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
            timeout=timeout,
            max_retries=3,
        )

    def model_id(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings using the OpenAI embeddings API."""
        import logging, time as _time
        _logger = logging.getLogger(__name__)
        total_chars = sum(len(t) for t in texts)
        _logger.info(f"Embed request: model={self._model} texts={len(texts)} total_chars={total_chars}")
        _t0 = _time.monotonic()
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        _elapsed = _time.monotonic() - _t0
        _logger.info(f"Embed response: model={self._model} elapsed={_elapsed:.1f}s dims={len(response.data[0].embedding) if response.data else '?'}")
        return [item.embedding for item in response.data]
