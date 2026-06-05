"""RouterLLMClient — the concrete LLMClient over Socratiq's existing stack.

``complete()`` delegates to the battle-tested ``AgentRuntime.call`` (provider
fallback + validator retry + tracing) so the one-shot generators get identical
behavior. ``stream()`` (the streaming agent-loop turn that emits AG-UI events)
is implemented in Phase 1 together with ``AgentLoop``/``AgentRunner`` — they
share the StreamChunk→AG-UI translation and are co-tested there.

Both paths reuse ``app.services.llm._call_support`` indirectly via AgentRuntime,
so fallback/validation/token logic is never duplicated.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from app.agentcore.events import types as ev
from app.agentcore.llm.client import TurnResult
from app.agentcore.tools.base import ToolCall
from app.services.llm._call_support import (
    ProviderRef,
    extract_text,
    resolve_provider,
    usage_tokens,
)
from app.services.llm.base import (
    LLMError,
    TokenUsage,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.router import ModelRouter
from app.services.llm.runtime import AgentRuntime, CallResult

logger = logging.getLogger(__name__)

__all__ = ["RouterLLMClient"]


class RouterLLMClient:
    def __init__(
        self,
        router: ModelRouter,
        *,
        primary: ProviderRef,
        fallbacks: Sequence[ProviderRef] = (),
        tracer=None,
    ) -> None:
        self._router = router
        self._runtime = AgentRuntime(router=router, tracer=tracer)
        self._primary = primary
        self._fallbacks = tuple(fallbacks)

    async def complete(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        validator=None,
        max_validation_retries: int = 1,
        phase: str = "llm_call",
    ) -> CallResult:
        return await self._runtime.call(
            messages,
            primary=self._primary,
            fallbacks=self._fallbacks,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            validator=validator,
            max_validation_retries=max_validation_retries,
            phase=phase,
        )

    async def _resolve(self):
        """Resolve the primary provider, falling back through the chain."""
        last: Exception | None = None
        for ref in (self._primary, *self._fallbacks):
            try:
                return await resolve_provider(ref, self._router)
            except LLMError as exc:
                last = exc
        raise last or LLMError("no provider could be resolved")

    async def stream(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        bus=None,
        parent_message_id: str | None = None,
    ) -> TurnResult:
        """One streamed assistant turn: emit AG-UI events on ``bus``, return a
        ``TurnResult`` (text + reasoning + tool calls + usage) for the loop.

        Providers that can't stream (e.g. CodexProvider) degrade to a single
        ``chat()`` whose output is replayed as the same AG-UI event shape, so
        the loop is agnostic to provider streaming support.
        """
        provider = await self._resolve()
        model = _safe_model_id(provider)
        if provider.supports_streaming():
            return await self._stream_native(
                provider, model, messages, tools, max_tokens, temperature, bus
            )
        return await self._stream_via_chat(
            provider, model, messages, tools, max_tokens, temperature, bus
        )

    async def _stream_native(
        self, provider, model, messages, tools, max_tokens, temperature, bus
    ) -> TurnResult:
        msg_id = bus.new_message_id() if bus else "msg"
        reasoning_id = f"{msg_id}_r"
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        text_open = reasoning_open = False
        tool_calls: list[ToolCall] = []
        tool_buf: dict[str, dict] = {}
        current_tid: str | None = None
        usage: TokenUsage | None = None

        async for chunk in provider.chat_stream(
            messages, tools=tools, max_tokens=max_tokens, temperature=temperature
        ):
            if chunk.type == "text_delta" and chunk.text:
                if not text_open:
                    await _emit(bus, ev.text_message_start(msg_id))
                    text_open = True
                text_parts.append(chunk.text)
                await _emit(bus, ev.text_message_content(msg_id, chunk.text))
            elif chunk.type == "reasoning_delta" and chunk.reasoning_content:
                if not reasoning_open:
                    await _emit(bus, ev.reasoning_start(reasoning_id))
                    reasoning_open = True
                reasoning_parts.append(chunk.reasoning_content)
                await _emit(bus, ev.reasoning_content(reasoning_id, chunk.reasoning_content))
            elif chunk.type == "tool_use_start":
                current_tid = chunk.tool_use_id or (bus.new_tool_call_id() if bus else "tc")
                tool_buf[current_tid] = {"name": chunk.tool_name or "", "input": ""}
                await _emit(bus, ev.tool_call_start(current_tid, chunk.tool_name or "", parent_message_id=msg_id))
            elif chunk.type == "tool_use_delta" and current_tid is not None:
                tool_buf[current_tid]["input"] += chunk.tool_input_delta or ""
                if chunk.tool_input_delta:
                    await _emit(bus, ev.tool_call_args(current_tid, chunk.tool_input_delta))
            elif chunk.type == "tool_use_end" and current_tid is not None:
                await _emit(bus, ev.tool_call_end(current_tid))
                buf = tool_buf[current_tid]
                tool_calls.append(ToolCall(id=current_tid, name=buf["name"], input=_parse_json(buf["input"])))
                current_tid = None
            elif chunk.type == "message_end":
                usage = chunk.usage

        if reasoning_open:
            await _emit(bus, ev.reasoning_end(reasoning_id))
        if text_open:
            await _emit(bus, ev.text_message_end(msg_id))

        return TurnResult(
            text="".join(text_parts),
            reasoning="".join(reasoning_parts),
            tool_calls=tool_calls,
            usage=usage,
            provider_used=model,
        )

    async def _stream_via_chat(
        self, provider, model, messages, tools, max_tokens, temperature, bus
    ) -> TurnResult:
        resp = await provider.chat(
            messages, tools=tools, max_tokens=max_tokens, temperature=temperature
        )
        text = extract_text(resp)
        msg_id = bus.new_message_id() if bus else "msg"
        if text:
            await _emit(bus, ev.text_message_start(msg_id))
            await _emit(bus, ev.text_message_content(msg_id, text))
            await _emit(bus, ev.text_message_end(msg_id))

        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "tool_use":
                tid = block.tool_use_id or (bus.new_tool_call_id() if bus else "tc")
                await _emit(bus, ev.tool_call_start(tid, block.tool_name or "", parent_message_id=msg_id))
                args = json.dumps(block.tool_input or {})
                await _emit(bus, ev.tool_call_args(tid, args))
                await _emit(bus, ev.tool_call_end(tid))
                tool_calls.append(
                    ToolCall(id=tid, name=block.tool_name or "", input=block.tool_input or {})
                )

        in_toks, out_toks = usage_tokens(resp)
        return TurnResult(
            text=text,
            reasoning=resp.reasoning_content or "",
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=in_toks, output_tokens=out_toks),
            provider_used=model,
            stop_reason=resp.stop_reason,
        )


async def _emit(bus, event) -> None:
    if bus is not None:
        await bus.emit(event)


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


def _safe_model_id(provider) -> str:
    try:
        return provider.model_id()
    except Exception:  # noqa: BLE001
        return type(provider).__name__
