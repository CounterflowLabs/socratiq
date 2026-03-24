"""Tests for tool adapter bidirectional conversions."""

import json

import pytest

from app.services.llm.base import ContentBlock, ToolDefinition, UnifiedMessage
from app.services.llm.adapters.tool_adapter import (
    anthropic_tool_use_to_blocks,
    openai_tool_calls_to_blocks,
    parse_prompt_tool_calls,
    tool_result_to_anthropic,
    tool_result_to_openai,
    tools_to_anthropic,
    tools_to_openai,
    tools_to_prompt,
)


@pytest.fixture
def sample_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="search",
            description="Search the knowledge base",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        ToolDefinition(
            name="get_profile",
            description="Get student profile",
            parameters={"type": "object", "properties": {}},
        ),
    ]


class TestToolsToAnthropic:
    def test_basic(self, sample_tools):
        result = tools_to_anthropic(sample_tools)
        assert len(result) == 2
        assert result[0]["name"] == "search"
        assert result[0]["input_schema"]["type"] == "object"
        assert "description" in result[0]

    def test_empty(self):
        assert tools_to_anthropic([]) == []


class TestToolsToOpenAI:
    def test_basic(self, sample_tools):
        result = tools_to_openai(sample_tools)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["parameters"]["type"] == "object"

    def test_empty(self):
        assert tools_to_openai([]) == []


class TestToolsToPrompt:
    def test_contains_tool_info(self, sample_tools):
        result = tools_to_prompt(sample_tools)
        assert "<tool>" in result
        assert "search" in result
        assert "get_profile" in result
        assert "<tool_call>" in result

    def test_empty_tools(self):
        result = tools_to_prompt([])
        assert "<tool_call>" in result  # still has instructions


class TestAnthropicToolUseToBlocks:
    def test_basic(self):
        blocks = anthropic_tool_use_to_blocks([
            {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"query": "attention"}},
        ])
        assert len(blocks) == 1
        assert blocks[0].type == "tool_use"
        assert blocks[0].tool_use_id == "tu_1"
        assert blocks[0].tool_name == "search"
        assert blocks[0].tool_input == {"query": "attention"}

    def test_multiple(self):
        blocks = anthropic_tool_use_to_blocks([
            {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"query": "a"}},
            {"type": "tool_use", "id": "tu_2", "name": "get_profile", "input": {}},
        ])
        assert len(blocks) == 2


class TestOpenAIToolCallsToBlocks:
    def test_basic(self):
        blocks = openai_tool_calls_to_blocks([
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "attention"}'},
            }
        ])
        assert len(blocks) == 1
        assert blocks[0].tool_name == "search"
        assert blocks[0].tool_input == {"query": "attention"}

    def test_invalid_json_arguments(self):
        blocks = openai_tool_calls_to_blocks([
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": "not json"},
            }
        ])
        assert len(blocks) == 1
        assert blocks[0].tool_input == {}


class TestParsePromptToolCalls:
    def test_single_call(self):
        text = 'I will search for that.\n<tool_call>\n{"name": "search", "arguments": {"query": "attention"}}\n</tool_call>'
        blocks = parse_prompt_tool_calls(text)
        assert len(blocks) == 1
        assert blocks[0].tool_name == "search"
        assert blocks[0].tool_input == {"query": "attention"}

    def test_multiple_calls(self):
        text = (
            '<tool_call>\n{"name": "search", "arguments": {"query": "a"}}\n</tool_call>\n'
            "Some text\n"
            '<tool_call>\n{"name": "get_profile", "arguments": {}}\n</tool_call>'
        )
        blocks = parse_prompt_tool_calls(text)
        assert len(blocks) == 2

    def test_no_calls(self):
        assert parse_prompt_tool_calls("Just regular text") == []

    def test_invalid_json(self):
        text = "<tool_call>\nnot valid json\n</tool_call>"
        assert parse_prompt_tool_calls(text) == []


class TestToolResultToAnthropic:
    def test_basic(self):
        msg = UnifiedMessage(
            role="tool_result",
            content=[
                ContentBlock(type="tool_result", tool_use_id="tu_1", tool_result_content="result data"),
            ],
        )
        result = tool_result_to_anthropic(msg)
        assert result["role"] == "user"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == "tu_1"

    def test_error_result(self):
        msg = UnifiedMessage(
            role="tool_result",
            content=[
                ContentBlock(type="tool_result", tool_use_id="tu_1", tool_result_content="error", is_error=True),
            ],
        )
        result = tool_result_to_anthropic(msg)
        assert result["content"][0]["is_error"] is True


class TestToolResultToOpenAI:
    def test_basic(self):
        msg = UnifiedMessage(
            role="tool_result",
            content=[
                ContentBlock(type="tool_result", tool_use_id="call_1", tool_result_content="result"),
            ],
        )
        result = tool_result_to_openai(msg)
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_1"
