"""Bidirectional tool use format conversion between unified and provider-specific formats."""

import json
import re

from app.services.llm.base import ContentBlock, ToolDefinition, UnifiedMessage


# === Tool Definition Conversion (outbound: unified → provider) ===

def tools_to_anthropic(tools: list[ToolDefinition]) -> list[dict]:
    """Convert unified ToolDefinitions to Anthropic tools format.

    Anthropic format: {"name": ..., "description": ..., "input_schema": ...}
    """
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def tools_to_openai(tools: list[ToolDefinition]) -> list[dict]:
    """Convert unified ToolDefinitions to OpenAI tools format.

    OpenAI format: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def tools_to_prompt(tools: list[ToolDefinition]) -> str:
    """Serialize tool definitions into a system prompt for models without native tool use.

    Uses XML-like tags that models can parse.
    """
    parts = ["You have access to the following tools:\n"]
    for t in tools:
        parts.append(f"<tool>\n<name>{t.name}</name>")
        parts.append(f"<description>{t.description}</description>")
        parts.append(f"<parameters>{json.dumps(t.parameters, indent=2)}</parameters>")
        parts.append("</tool>\n")
    parts.append(
        "To use a tool, respond with:\n"
        "<tool_call>\n"
        '{"name": "tool_name", "arguments": {"arg1": "value1"}}\n'
        "</tool_call>\n"
        "You may include text before or after the tool call."
    )
    return "\n".join(parts)


# === Tool Use Response Conversion (inbound: provider → unified) ===

def anthropic_tool_use_to_blocks(tool_use_blocks: list[dict]) -> list[ContentBlock]:
    """Convert Anthropic tool_use content blocks to unified ContentBlocks.

    Anthropic format: {"type": "tool_use", "id": ..., "name": ..., "input": ...}
    """
    return [
        ContentBlock(
            type="tool_use",
            tool_use_id=block["id"],
            tool_name=block["name"],
            tool_input=block["input"],
        )
        for block in tool_use_blocks
    ]


def openai_tool_calls_to_blocks(tool_calls: list[dict]) -> list[ContentBlock]:
    """Convert OpenAI tool_calls to unified ContentBlocks.

    OpenAI format: {"id": ..., "type": "function", "function": {"name": ..., "arguments": "..."}}
    """
    blocks = []
    for tc in tool_calls:
        func = tc["function"]
        try:
            args = json.loads(func["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        blocks.append(
            ContentBlock(
                type="tool_use",
                tool_use_id=tc["id"],
                tool_name=func["name"],
                tool_input=args,
            )
        )
    return blocks


def parse_prompt_tool_calls(text: str) -> list[ContentBlock]:
    """Parse tool calls from LLM text output (prompt injection fallback).

    Looks for <tool_call>...</tool_call> blocks containing JSON.
    Returns empty list if no tool calls found.
    """
    pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
    matches = re.findall(pattern, text, re.DOTALL)
    blocks = []
    for i, match in enumerate(matches):
        try:
            data = json.loads(match)
            blocks.append(
                ContentBlock(
                    type="tool_use",
                    tool_use_id=f"prompt_tc_{i}",
                    tool_name=data.get("name", ""),
                    tool_input=data.get("arguments", {}),
                )
            )
        except json.JSONDecodeError:
            continue
    return blocks


# === Tool Result Conversion (outbound: unified → provider) ===

def tool_result_to_anthropic(message: UnifiedMessage) -> dict:
    """Convert a unified tool_result message to Anthropic format.

    Anthropic expects: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}
    """
    blocks = message.content if isinstance(message.content, list) else []
    result_blocks = []
    for block in blocks:
        if block.type == "tool_result":
            result_block = {
                "type": "tool_result",
                "tool_use_id": block.tool_use_id,
                "content": block.tool_result_content or "",
            }
            if block.is_error:
                result_block["is_error"] = True
            result_blocks.append(result_block)
    return {"role": "user", "content": result_blocks}


def tool_result_to_openai(message: UnifiedMessage) -> list[dict]:
    """Convert a unified tool_result message to OpenAI format.

    OpenAI expects separate messages with role="tool" for each result.
    """
    blocks = message.content if isinstance(message.content, list) else []
    messages = []
    for block in blocks:
        if block.type == "tool_result":
            messages.append({
                "role": "tool",
                "tool_call_id": block.tool_use_id,
                "content": block.tool_result_content or "",
            })
    return messages
