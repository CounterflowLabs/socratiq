"""Official Codex app-server provider."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from app.services.llm.adapters.tool_adapter import parse_prompt_tool_calls, tools_to_prompt
from app.services.llm.base import (
    ContentBlock,
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    StreamChunk,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.codex_auth import get_codex_app_server_command, get_codex_env


class CodexProvider(LLMProvider):
    """LLM provider backed by the official `codex app-server`."""

    def __init__(
        self,
        model: str,
        *,
        supports_tools: bool = False,
        supports_stream: bool = False,
        max_tokens_limit: int = 4096,
        timeout: float = 180.0,
    ) -> None:
        self._model = model
        self._supports_tools = supports_tools
        self._supports_stream = supports_stream
        self._max_tokens_limit = max_tokens_limit
        self._timeout = timeout

    def _stringify_content(self, content: str | list[ContentBlock]) -> str:
        if isinstance(content, str):
            return content.strip()

        parts: list[str] = []
        for block in content:
            if block.type == "text" and block.text:
                parts.append(block.text)
            elif block.type == "tool_use":
                parts.append(
                    "<tool_call>\n"
                    + json.dumps(
                        {
                            "name": block.tool_name or "",
                            "arguments": block.tool_input or {},
                        },
                        ensure_ascii=False,
                    )
                    + "\n</tool_call>"
                )
            elif block.type == "tool_result" and block.tool_result_content:
                parts.append(block.tool_result_content)
        return "\n".join(part for part in parts if part).strip()

    def _build_prompt(
        self,
        messages: list[UnifiedMessage],
        tools: list[ToolDefinition] | None,
    ) -> tuple[str | None, str]:
        system_parts: list[str] = []
        conversation_parts: list[str] = []

        for msg in messages:
            if msg.role == "system":
                text = self._stringify_content(msg.content)
                if text:
                    system_parts.append(text)
                continue

            if msg.role == "tool_result":
                text = self._stringify_content(msg.content)
                if text:
                    conversation_parts.append(f"Tool result:\n{text}")
                continue

            role_label = "User" if msg.role == "user" else "Assistant"
            text = self._stringify_content(msg.content)
            if text:
                conversation_parts.append(f"{role_label}:\n{text}")

        if tools:
            system_parts.append(tools_to_prompt(tools))

        base_instructions = "\n\n".join(part for part in system_parts if part).strip() or None
        prompt_sections = [
            "Continue the following conversation and provide the next assistant response.",
        ]
        if conversation_parts:
            prompt_sections.append("\n\n".join(conversation_parts))
        prompt_sections.append("Respond only as the assistant.")
        return base_instructions, "\n\n".join(prompt_sections)

    async def _run_codex(
        self,
        *,
        prompt: str,
        base_instructions: str | None,
        temperature: float,
    ) -> str:
        try:
            from codex_app_server_sdk import CodexClient, ThreadConfig, TurnOverrides
        except ImportError as exc:
            raise LLMProviderError(
                "Codex app-server SDK is not installed in the backend container."
            ) from exc

        effort: str = "medium"
        if temperature <= 0.2:
            effort = "high"
        elif temperature >= 0.9:
            effort = "low"

        try:
            async with CodexClient.connect_stdio(
                command=get_codex_app_server_command(),
                env=get_codex_env(),
                request_timeout=self._timeout,
                inactivity_timeout=self._timeout,
            ) as client:
                result = await client.chat_once(
                    prompt,
                    thread_config=ThreadConfig(
                        model=self._model,
                        base_instructions=base_instructions,
                        approval_policy="never",
                        sandbox="read-only",
                        ephemeral=True,
                    ),
                    turn_overrides=TurnOverrides(
                        model=self._model,
                        effort=effort,
                        summary="none",
                        approval_policy="never",
                        sandbox_policy={
                            "type": "readOnly",
                            "access": {"type": "fullAccess"},
                        },
                    ),
                )
        except Exception as exc:
            message = str(exc)
            if re.search(r"not logged in|sign in|auth", message, re.IGNORECASE):
                raise LLMAuthError(
                    "Codex CLI 未登录。请先在 /setup 使用 ChatGPT 登录。"
                ) from exc
            raise LLMProviderError(f"Codex app-server request failed: {message}") from exc

        return result.final_text.strip()

    async def chat(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Send a chat request through Codex app-server."""
        del kwargs, max_tokens  # Codex app-server manages token limits internally.
        base_instructions, prompt = self._build_prompt(messages, tools)
        text = await self._run_codex(
            prompt=prompt,
            base_instructions=base_instructions,
            temperature=temperature,
        )

        blocks: list[ContentBlock] = []
        if tools:
            tool_calls = parse_prompt_tool_calls(text)
            clean_text = re.sub(
                r"<tool_call>.*?</tool_call>",
                "",
                text,
                flags=re.DOTALL,
            ).strip()
            if clean_text:
                blocks.append(ContentBlock(type="text", text=clean_text))
            blocks.extend(tool_calls)
        elif text:
            blocks.append(ContentBlock(type="text", text=text))

        return LLMResponse(content=blocks, model=self._model)

    async def chat_stream(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Fallback streaming wrapper around the non-streaming Codex call."""
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
                    tool_input_delta=json.dumps(block.tool_input or {}, ensure_ascii=False),
                )
                yield StreamChunk(type="tool_use_end")
        yield StreamChunk(type="message_end", usage=response.usage)

    def supports_tool_use(self) -> bool:
        """Whether this provider supports native tool use."""
        return self._supports_tools

    def supports_streaming(self) -> bool:
        """Whether this provider supports native streaming."""
        return self._supports_stream

    def model_id(self) -> str:
        """The configured Codex model identifier."""
        return self._model

