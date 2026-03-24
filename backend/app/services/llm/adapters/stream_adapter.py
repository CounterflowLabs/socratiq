"""Stream normalization: convert provider-specific SSE events to unified StreamChunks."""

from collections.abc import AsyncIterator

from app.services.llm.base import StreamChunk, TokenUsage


async def normalize_anthropic_stream(raw_stream) -> AsyncIterator[StreamChunk]:
    """Normalize Anthropic streaming events to unified StreamChunks.

    Anthropic event types:
    - message_start: contains message metadata
    - content_block_start: starts a text or tool_use block
    - content_block_delta: incremental content (text_delta or input_json_delta)
    - content_block_stop: ends a content block
    - message_delta: final stop_reason and usage
    - message_stop: stream complete
    """
    async for event in raw_stream:
        event_type = getattr(event, "type", None)

        if event_type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                yield StreamChunk(
                    type="tool_use_start",
                    tool_use_id=block.id,
                    tool_name=block.name,
                )

        elif event_type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                yield StreamChunk(type="text_delta", text=delta.text)
            elif delta.type == "input_json_delta":
                yield StreamChunk(
                    type="tool_use_delta",
                    tool_input_delta=delta.partial_json,
                )

        elif event_type == "content_block_stop":
            # Check if we were in a tool_use block
            # Emit tool_use_end for completeness
            yield StreamChunk(type="tool_use_end")

        elif event_type == "message_delta":
            usage_data = getattr(event, "usage", None)
            usage = None
            if usage_data:
                usage = TokenUsage(
                    input_tokens=getattr(usage_data, "input_tokens", 0),
                    output_tokens=getattr(usage_data, "output_tokens", 0),
                )
            yield StreamChunk(type="message_end", usage=usage)


async def normalize_openai_stream(raw_stream) -> AsyncIterator[StreamChunk]:
    """Normalize OpenAI streaming chunks to unified StreamChunks.

    OpenAI chunk format:
    - choices[0].delta.content: text content
    - choices[0].delta.tool_calls: tool call deltas
    - choices[0].finish_reason: "stop" or "tool_calls" when done
    - usage: token counts (if stream_options.include_usage was set)
    """
    active_tool_calls: dict[int, bool] = {}  # index → started

    async for chunk in raw_stream:
        if not chunk.choices:
            # Final chunk may have usage only
            if hasattr(chunk, "usage") and chunk.usage:
                yield StreamChunk(
                    type="message_end",
                    usage=TokenUsage(
                        input_tokens=chunk.usage.prompt_tokens or 0,
                        output_tokens=chunk.usage.completion_tokens or 0,
                    ),
                )
            continue

        choice = chunk.choices[0]
        delta = choice.delta

        # Text content
        if delta.content:
            yield StreamChunk(type="text_delta", text=delta.content)

        # Tool calls
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index

                if idx not in active_tool_calls:
                    # New tool call starting
                    active_tool_calls[idx] = True
                    yield StreamChunk(
                        type="tool_use_start",
                        tool_use_id=tc_delta.id,
                        tool_name=tc_delta.function.name if tc_delta.function and tc_delta.function.name else None,
                    )

                # Argument delta
                if tc_delta.function and tc_delta.function.arguments:
                    yield StreamChunk(
                        type="tool_use_delta",
                        tool_input_delta=tc_delta.function.arguments,
                    )

        # Finish reason
        if choice.finish_reason:
            # End any active tool calls
            for idx in active_tool_calls:
                yield StreamChunk(type="tool_use_end")
            active_tool_calls.clear()

            usage = None
            if hasattr(chunk, "usage") and chunk.usage:
                usage = TokenUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
            yield StreamChunk(type="message_end", usage=usage)
