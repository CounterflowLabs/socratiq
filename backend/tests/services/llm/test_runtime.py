"""Unit tests for AgentRuntime — provider fallback, validated retry, tracing."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.base import (
    ContentBlock,
    LLMError,
    LLMProviderError,
    LLMResponse,
    TokenUsage,
    UnifiedMessage,
)
from app.services.llm.router import TaskType
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    Tracer,
    ValidationFailed,
)


# --- helpers --------------------------------------------------------------


class RecordingTracer:
    """Tracer that captures every emitted event for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def fields_for(self, event: str) -> list[dict[str, Any]]:
        return [f for name, f in self.events if name == event]


def _provider(model_id: str = "primary-model") -> AsyncMock:
    """AsyncMock LLMProvider with ``model_id()`` patched to a sync method."""
    p = AsyncMock()
    p.model_id = MagicMock(return_value=model_id)
    return p


def _response(text: str, *, in_tok: int = 100, out_tok: int = 50) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=text)],
        model="mock",
        usage=TokenUsage(input_tokens=in_tok, output_tokens=out_tok),
    )


def _msgs() -> list[UnifiedMessage]:
    return [UnifiedMessage(role="user", content="hi")]


# --- happy paths ----------------------------------------------------------


class TestPrimarySuccess:
    async def test_returns_response_text_and_token_usage(self):
        provider = _provider("primary")
        provider.chat.return_value = _response("hello", in_tok=12, out_tok=7)
        runtime = AgentRuntime(tracer=RecordingTracer())

        result = await runtime.call(_msgs(), primary=provider, phase="t.unit")

        assert result.text == "hello"
        assert result.parsed is None
        assert result.provider_used == "primary"
        assert result.fallback_depth == 0
        assert result.attempts == 1
        assert result.input_tokens == 12
        assert result.output_tokens == 7

    async def test_emits_phase_start_provider_call_phase_end(self):
        provider = _provider()
        provider.chat.return_value = _response("ok")
        tracer = RecordingTracer()
        runtime = AgentRuntime(tracer=tracer)

        await runtime.call(_msgs(), primary=provider, phase="t.unit")

        names = tracer.names()
        assert names == ["phase_start", "provider_call", "phase_end"]
        end = tracer.fields_for("phase_end")[0]
        assert end["status"] == "ok"
        assert end["provider_used"] == "primary-model"
        assert end["attempts"] == 1


# --- provider fallback ----------------------------------------------------


class TestProviderFallback:
    async def test_falls_back_on_llm_error(self):
        primary = _provider("primary")
        primary.chat.side_effect = LLMProviderError("boom")
        secondary = _provider("secondary")
        secondary.chat.return_value = _response("from-fallback")
        tracer = RecordingTracer()
        runtime = AgentRuntime(tracer=tracer)

        result = await runtime.call(
            _msgs(), primary=primary, fallbacks=[secondary], phase="t.fb"
        )

        assert result.text == "from-fallback"
        assert result.provider_used == "secondary"
        assert result.fallback_depth == 1
        assert "provider_fallback" in tracer.names()
        fb = tracer.fields_for("provider_fallback")[0]
        assert fb["from_provider"] == "primary"
        assert "boom" in fb["error"]

    async def test_wraps_arbitrary_exception_as_llm_error_for_fallback(self):
        # Network glitch / unexpected client bug should still trigger fallback.
        primary = _provider("primary")
        primary.chat.side_effect = RuntimeError("network glitch")
        secondary = _provider("secondary")
        secondary.chat.return_value = _response("recovered")
        runtime = AgentRuntime(tracer=RecordingTracer())

        result = await runtime.call(
            _msgs(), primary=primary, fallbacks=[secondary], phase="t.fb2"
        )
        assert result.text == "recovered"

    async def test_raises_when_all_providers_fail(self):
        primary = _provider("p1")
        primary.chat.side_effect = LLMProviderError("first")
        secondary = _provider("p2")
        secondary.chat.side_effect = LLMProviderError("second")
        tracer = RecordingTracer()
        runtime = AgentRuntime(tracer=tracer)

        with pytest.raises(LLMError) as exc_info:
            await runtime.call(
                _msgs(), primary=primary, fallbacks=[secondary], phase="t.exhaust"
            )
        assert "second" in str(exc_info.value)
        end = tracer.fields_for("phase_end")[0]
        assert end["status"] == "all_providers_failed"


# --- TaskType resolution --------------------------------------------------


class TestRouterResolution:
    async def test_resolves_task_type_via_router(self):
        provider = _provider("routed")
        provider.chat.return_value = _response("ok")
        router = MagicMock()
        router.get_provider = AsyncMock(return_value=provider)

        runtime = AgentRuntime(router=router, tracer=RecordingTracer())
        result = await runtime.call(
            _msgs(), primary=TaskType.STRUCTURE_PLANNING, phase="t.router"
        )

        assert result.provider_used == "routed"
        router.get_provider.assert_awaited_once_with(TaskType.STRUCTURE_PLANNING)

    async def test_falls_through_when_task_type_unroutable(self):
        # Mirrors the SectionPlanner pattern: STRUCTURE_PLANNING unconfigured,
        # EVALUATION as fallback.
        primary_provider = _provider("structure")
        primary_provider.chat.return_value = _response("from-structure")
        router = MagicMock()

        async def _fake_get(task_type):
            if task_type == TaskType.STRUCTURE_PLANNING:
                raise LLMError("no model configured for task type: structure_planning")
            return primary_provider

        router.get_provider = AsyncMock(side_effect=_fake_get)
        tracer = RecordingTracer()
        runtime = AgentRuntime(router=router, tracer=tracer)

        result = await runtime.call(
            _msgs(),
            primary=TaskType.STRUCTURE_PLANNING,
            fallbacks=[TaskType.EVALUATION],
            phase="t.routerfb",
        )

        assert result.text == "from-structure"
        assert result.fallback_depth == 1
        assert "provider_resolve_failed" in tracer.names()


# --- validated retry ------------------------------------------------------


class TestValidatedRetry:
    async def test_validator_success_first_try(self):
        provider = _provider()
        provider.chat.return_value = _response('{"x": 1}')
        runtime = AgentRuntime(tracer=RecordingTracer())

        def parse(text: str):
            import json
            return json.loads(text)

        result = await runtime.call(
            _msgs(), primary=provider, validator=parse, phase="t.val"
        )
        assert result.parsed == {"x": 1}
        assert result.attempts == 1

    async def test_retries_then_succeeds(self):
        provider = _provider()
        provider.chat.side_effect = [
            _response("not json", in_tok=10, out_tok=5),
            _response('{"x": 2}', in_tok=15, out_tok=8),
        ]
        tracer = RecordingTracer()
        runtime = AgentRuntime(tracer=tracer)

        def parse(text: str):
            import json
            try:
                return json.loads(text)
            except Exception as exc:
                raise ValidationFailed("bad json", hint="emit only JSON") from exc

        result = await runtime.call(
            _msgs(), primary=provider, validator=parse, phase="t.retry"
        )

        assert result.parsed == {"x": 2}
        assert result.attempts == 2
        # Tokens cumulate across the validator retries.
        assert result.input_tokens == 25
        assert result.output_tokens == 13
        assert "validation_failed" in tracer.names()
        assert "validation_retry" in tracer.names()

    async def test_passes_corrective_message_to_provider(self):
        provider = _provider()
        provider.chat.side_effect = [
            _response("nope"),
            _response('{"ok": true}'),
        ]
        runtime = AgentRuntime(tracer=RecordingTracer())

        def parse(text: str):
            import json
            try:
                return json.loads(text)
            except Exception as exc:
                raise ValidationFailed("not parseable", hint="JSON only") from exc

        await runtime.call(
            _msgs(),
            primary=provider,
            validator=parse,
            phase="t.corrective",
        )

        # Second call should have received the corrective context.
        second_call_msgs = provider.chat.await_args_list[1].kwargs["messages"]
        roles = [m.role for m in second_call_msgs]
        assert roles == ["user", "assistant", "user"]
        # The corrective tail is the 3rd message.
        assert "JSON only" in second_call_msgs[-1].content

    async def test_retry_directive_overrides_hint(self):
        provider = _provider()
        provider.chat.side_effect = [
            _response("bad"),
            _response('{"ok": true}'),
        ]
        runtime = AgentRuntime(tracer=RecordingTracer())

        def parse(text: str):
            import json
            try:
                return json.loads(text)
            except Exception as exc:
                raise ValidationFailed("not parseable", hint="ignored") from exc

        await runtime.call(
            _msgs(),
            primary=provider,
            validator=parse,
            retry_directive="STRICT JSON ONLY.",
            phase="t.directive",
        )

        second_call_msgs = provider.chat.await_args_list[1].kwargs["messages"]
        assert second_call_msgs[-1].content == "STRICT JSON ONLY."

    async def test_raises_validation_error_when_exhausted(self):
        provider = _provider()
        provider.chat.return_value = _response("never valid")
        tracer = RecordingTracer()
        runtime = AgentRuntime(tracer=tracer)

        def parse(text: str):
            raise ValidationFailed("nope")

        with pytest.raises(LLMValidationError) as exc_info:
            await runtime.call(
                _msgs(),
                primary=provider,
                validator=parse,
                max_validation_retries=1,
                phase="t.exhaust_val",
            )
        assert exc_info.value.attempts == 2
        end = tracer.fields_for("phase_end")[0]
        assert end["status"] == "validation_exhausted"

    async def test_validation_exhaustion_does_not_trigger_provider_fallback(self):
        # Schema problems don't get better with a different model — verify we
        # surface the validation error instead of silently swapping providers.
        primary = _provider("primary")
        primary.chat.return_value = _response("garbage")
        secondary = _provider("secondary")
        secondary.chat.return_value = _response('{"ok": true}')
        runtime = AgentRuntime(tracer=RecordingTracer())

        def parse(text: str):
            raise ValidationFailed("nope")

        with pytest.raises(LLMValidationError):
            await runtime.call(
                _msgs(),
                primary=primary,
                fallbacks=[secondary],
                validator=parse,
                max_validation_retries=0,
                phase="t.no_swap_on_validation",
            )
        secondary.chat.assert_not_awaited()
