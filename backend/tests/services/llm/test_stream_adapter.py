"""Tests for stream adapter normalization."""

import pytest
from types import SimpleNamespace

from app.services.llm.adapters.stream_adapter import (
    normalize_anthropic_stream,
    normalize_openai_stream,
)
from app.services.llm.base import StreamChunk


# === Helper: create async iterators from lists ===

async def async_iter(items):
    for item in items:
        yield item


# === Anthropic Stream Tests ===

class TestNormalizeAnthropicStream:
    @pytest.mark.asyncio
    async def test_text_only(self):
        events = [
            SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="text", text="")),
            SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="Hello ")),
            SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="world")),
            SimpleNamespace(type="content_block_stop"),
            SimpleNamespace(type="message_delta", usage=SimpleNamespace(input_tokens=10, output_tokens=5)),
        ]
        chunks = [c async for c in normalize_anthropic_stream(async_iter(events))]
        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].text == "Hello "
        assert text_chunks[1].text == "world"
        # Should end with message_end
        assert chunks[-1].type == "message_end"
        assert chunks[-1].usage is not None
        assert chunks[-1].usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_tool_use(self):
        events = [
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", id="tu_1", name="search"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"query":'),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='"test"}'),
            ),
            SimpleNamespace(type="content_block_stop"),
            SimpleNamespace(type="message_delta", usage=None),
        ]
        chunks = [c async for c in normalize_anthropic_stream(async_iter(events))]
        assert chunks[0].type == "tool_use_start"
        assert chunks[0].tool_use_id == "tu_1"
        assert chunks[0].tool_name == "search"
        assert chunks[1].type == "tool_use_delta"
        assert chunks[2].type == "tool_use_delta"
        assert chunks[3].type == "tool_use_end"

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        chunks = [c async for c in normalize_anthropic_stream(async_iter([]))]
        assert chunks == []


# === OpenAI Stream Tests ===

class TestNormalizeOpenAIStream:
    @pytest.mark.asyncio
    async def test_text_only(self):
        chunks_in = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello ", tool_calls=None), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="world", tool_calls=None), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="stop")],
                usage=None,
            ),
        ]
        chunks = [c async for c in normalize_openai_stream(async_iter(chunks_in))]
        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].text == "Hello "
        assert chunks[-1].type == "message_end"

    @pytest.mark.asyncio
    async def test_tool_calls(self):
        tc_start = SimpleNamespace(
            index=0,
            id="call_1",
            function=SimpleNamespace(name="search", arguments=""),
        )
        tc_delta = SimpleNamespace(
            index=0,
            id=None,
            function=SimpleNamespace(name=None, arguments='{"query": "test"}'),
        )
        chunks_in = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc_start]), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc_delta]), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="tool_calls")],
                usage=None,
            ),
        ]
        chunks = [c async for c in normalize_openai_stream(async_iter(chunks_in))]
        assert chunks[0].type == "tool_use_start"
        assert chunks[0].tool_use_id == "call_1"
        assert chunks[0].tool_name == "search"
        assert chunks[1].type == "tool_use_delta"
        # Should have tool_use_end and message_end
        end_types = [c.type for c in chunks[-2:]]
        assert "tool_use_end" in end_types
        assert "message_end" in end_types

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        chunks = [c async for c in normalize_openai_stream(async_iter([]))]
        assert chunks == []
