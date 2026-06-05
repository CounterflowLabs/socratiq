"""AgentRuntime — thin wrapper around LLMProvider.chat() that adds:

1. Provider-fallback chains (primary → fallbacks on ``LLMError``)
2. Schema-validated retry (validator raises ``ValidationFailed`` → corrective retry)
3. Structured trace events at every phase, provider call, and failure

Existing generators migrate one call site at a time; nothing forces a global
cutover. Streaming (``chat_stream``) is intentionally out of scope — the
MentorAgent loop instruments itself directly with the same ``Tracer``.

Trace event taxonomy
--------------------

Every event carries ``phase`` (caller-supplied label, e.g.
``"section_planner.layer1"``) plus event-specific fields:

- ``phase_start``: provider_chain, max_tokens, temperature, message_count,
  has_tools, has_validator
- ``provider_call``: provider, fallback_depth, attempt, input_tokens,
  output_tokens, elapsed_ms, response_chars
- ``provider_resolve_failed``: fallback_depth, ref, error
- ``provider_fallback``: from_provider, from_depth, error
- ``validation_failed``: attempt, reason, hint
- ``validation_retry``: attempt
- ``phase_end``: status (ok | validation_exhausted | all_providers_failed),
  provider_used, fallback_depth, attempts, input_tokens, output_tokens,
  elapsed_ms
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.llm._call_support import (
    ProviderRef,
    build_retry_message as _build_retry_message,
    extract_text as _extract_text,
    ms_since as _ms_since,
    repr_provider_ref as _repr_provider_ref,
    resolve_provider as _resolve_provider,
    usage_tokens as _usage_tokens,
)
from app.services.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponse,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


# --- Tracer ---------------------------------------------------------------


class Tracer(Protocol):
    """Sink for runtime trace events. Implement to ship to OTel/Sentry/etc."""

    def emit(self, event: str, **fields: Any) -> None: ...


class LoggingTracer:
    """Default tracer — one structured log line per event under ``agent.trace``.

    Logs at INFO level so production deploys can drop the level to WARNING
    if the volume is too high. Switch to a richer Tracer (OTel exporter,
    eval-collector) by calling ``set_default_tracer``.
    """

    def __init__(self, logger_name: str = "agent.trace") -> None:
        self._log = logging.getLogger(logger_name)

    def emit(self, event: str, **fields: Any) -> None:
        try:
            payload = json.dumps(
                fields, default=str, ensure_ascii=False, sort_keys=True
            )
        except (TypeError, ValueError):
            payload = repr(fields)
        self._log.info("%s %s", event, payload)


_default_tracer: Tracer = LoggingTracer()


def set_default_tracer(tracer: Tracer) -> None:
    """Swap the process-wide default tracer (tests, OTel exporter, etc.)."""
    global _default_tracer
    _default_tracer = tracer


def get_default_tracer() -> Tracer:
    return _default_tracer


# --- Validator contract ---------------------------------------------------


class ValidationFailed(Exception):
    """Raised by a validator when the LLM response cannot be parsed/validated.

    The runtime catches this and either retries (with corrective context)
    or raises ``LLMValidationError`` on retry exhaustion. ``hint`` is
    appended to the corrective user message — use it to give the model a
    specific suggestion (e.g. "the response was missing the 'blocks' key").
    """

    def __init__(self, reason: str, hint: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.hint = hint


class LLMValidationError(LLMError):
    """Raised by the runtime when validator retries are exhausted.

    Inherits ``LLMError`` so generic ``except LLMError`` handlers still see
    it, but is treated specially inside the runtime: validation exhaustion
    does NOT trigger provider fallback (a different provider won't fix a
    schema mismatch).

    ``input_tokens`` and ``output_tokens`` carry the cumulative token usage
    across all validator attempts against the failing provider, so callers
    that aggregate run stats (SectionPlanner, eval harnesses) don't lose
    accounting on the failure path.
    """

    def __init__(
        self,
        reason: str,
        attempts: int,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        super().__init__(f"validator failed after {attempts} attempts: {reason}")
        self.reason = reason
        self.attempts = attempts
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


Validator = Callable[[str], Any]
"""(response_text) -> parsed object. Raise ``ValidationFailed`` on bad output."""


# --- Result ---------------------------------------------------------------


@dataclass
class CallResult:
    """Outcome of a single ``AgentRuntime.call``.

    ``parsed`` is ``None`` when no validator was supplied (or when the
    validator returned ``None`` legitimately). ``input_tokens`` /
    ``output_tokens`` are cumulative across validator retries against the
    successful provider — fallback-attempt token usage is reported via the
    per-call trace events instead.
    """

    response: LLMResponse
    text: str
    parsed: Any = None
    provider_used: str = ""
    fallback_depth: int = 0
    attempts: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: float = 0.0


# --- Runtime --------------------------------------------------------------
# ``ProviderRef`` is defined in ``_call_support`` and re-imported above so
# callers that do ``from app.services.llm.runtime import ProviderRef`` keep
# working.


class AgentRuntime:
    """Wraps ``LLMProvider.chat()`` with fallback, validation, and tracing."""

    def __init__(
        self,
        router: ModelRouter | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._router = router
        self._tracer = tracer or _default_tracer

    async def call(
        self,
        messages: list[UnifiedMessage],
        *,
        primary: ProviderRef,
        fallbacks: Sequence[ProviderRef] = (),
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[ToolDefinition] | None = None,
        phase: str = "llm_call",
        validator: Validator | None = None,
        max_validation_retries: int = 1,
        retry_directive: str | None = None,
    ) -> CallResult:
        """Run an LLM call with provider fallback + optional validated retry.

        Args:
            messages: chat history.
            primary: first provider to try (LLMProvider or TaskType).
            fallbacks: ordered fallback providers tried on ``LLMError``.
            max_tokens: forwarded to provider.
            temperature: forwarded to provider.
            tools: forwarded to provider.
            phase: caller-supplied label for trace events.
            validator: optional ``response_text → parsed`` function. Raise
                ``ValidationFailed(reason, hint)`` to trigger a corrective
                retry against the same provider.
            max_validation_retries: additional attempts after the first.
                Default ``1`` (= up to 2 calls per provider before giving up).
            retry_directive: text appended verbatim to the corrective retry
                message instead of the validator's hint. Use this when the
                generator already has a polished correction prompt.

        Returns:
            ``CallResult`` — ``parsed`` is ``None`` when no validator ran.

        Raises:
            LLMValidationError: validator failed and retries exhausted. Does
                not trigger provider fallback — schema problems don't get
                better with a different model.
            LLMError: every provider in the chain raised; the last error is
                re-raised.
        """
        chain: list[ProviderRef] = [primary, *fallbacks]
        last_error: Exception | None = None
        started = time.perf_counter()

        self._tracer.emit(
            "phase_start",
            phase=phase,
            provider_chain=[_repr_provider_ref(p) for p in chain],
            max_tokens=max_tokens,
            temperature=temperature,
            message_count=len(messages),
            has_tools=bool(tools),
            has_validator=validator is not None,
        )

        for depth, ref in enumerate(chain):
            try:
                provider = await self._resolve(ref)
            except LLMError as exc:
                last_error = exc
                self._tracer.emit(
                    "provider_resolve_failed",
                    phase=phase,
                    fallback_depth=depth,
                    ref=_repr_provider_ref(ref),
                    error=str(exc),
                )
                continue

            try:
                result = await self._call_with_validation(
                    provider=provider,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=tools,
                    phase=phase,
                    fallback_depth=depth,
                    validator=validator,
                    max_validation_retries=max_validation_retries,
                    retry_directive=retry_directive,
                )
            except LLMValidationError:
                # Validation exhaustion is NOT a provider failure — falling
                # through to a different provider would burn more tokens for
                # the same schema problem. Surface to the caller.
                self._tracer.emit(
                    "phase_end",
                    phase=phase,
                    status="validation_exhausted",
                    provider_used=provider.model_id(),
                    elapsed_ms=_ms_since(started),
                )
                raise
            except LLMError as exc:
                last_error = exc
                if depth + 1 < len(chain):
                    self._tracer.emit(
                        "provider_fallback",
                        phase=phase,
                        from_provider=provider.model_id(),
                        from_depth=depth,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                continue
            except Exception as exc:  # noqa: BLE001
                # Network glitch / unexpected provider client bug — wrap so
                # the next iteration's logic stays uniform.
                last_error = LLMError(f"{type(exc).__name__}: {exc}")
                if depth + 1 < len(chain):
                    self._tracer.emit(
                        "provider_fallback",
                        phase=phase,
                        from_provider=provider.model_id(),
                        from_depth=depth,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                continue

            result.elapsed_ms = _ms_since(started)
            self._tracer.emit(
                "phase_end",
                phase=phase,
                status="ok",
                provider_used=result.provider_used,
                fallback_depth=result.fallback_depth,
                attempts=result.attempts,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                elapsed_ms=result.elapsed_ms,
            )
            return result

        self._tracer.emit(
            "phase_end",
            phase=phase,
            status="all_providers_failed",
            elapsed_ms=_ms_since(started),
            error=str(last_error) if last_error else "empty_chain",
        )
        if isinstance(last_error, LLMError):
            raise last_error
        if last_error is not None:
            raise LLMError(str(last_error))
        raise LLMError("AgentRuntime.call invoked with empty provider chain")

    async def _resolve(self, ref: ProviderRef) -> LLMProvider:
        return await _resolve_provider(ref, self._router)

    async def _call_with_validation(
        self,
        *,
        provider: LLMProvider,
        messages: list[UnifiedMessage],
        max_tokens: int,
        temperature: float,
        tools: list[ToolDefinition] | None,
        phase: str,
        fallback_depth: int,
        validator: Validator | None,
        max_validation_retries: int,
        retry_directive: str | None,
    ) -> CallResult:
        attempt = 0
        msgs = list(messages)  # local copy — corrective retry mutates this, not caller's list
        cumulative_in = 0
        cumulative_out = 0

        while True:
            attempt += 1
            call_started = time.perf_counter()
            response = await provider.chat(
                messages=msgs,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            in_toks, out_toks = _usage_tokens(response)
            cumulative_in += in_toks
            cumulative_out += out_toks
            text = _extract_text(response)
            elapsed_ms = _ms_since(call_started)

            self._tracer.emit(
                "provider_call",
                phase=phase,
                provider=provider.model_id(),
                fallback_depth=fallback_depth,
                attempt=attempt,
                input_tokens=in_toks,
                output_tokens=out_toks,
                elapsed_ms=elapsed_ms,
                response_chars=len(text),
            )

            if validator is None:
                return CallResult(
                    response=response,
                    text=text,
                    parsed=None,
                    provider_used=provider.model_id(),
                    fallback_depth=fallback_depth,
                    attempts=attempt,
                    input_tokens=cumulative_in,
                    output_tokens=cumulative_out,
                )

            try:
                parsed = validator(text)
            except ValidationFailed as exc:
                self._tracer.emit(
                    "validation_failed",
                    phase=phase,
                    attempt=attempt,
                    reason=exc.reason,
                    hint=exc.hint,
                )
                if attempt > max_validation_retries:
                    raise LLMValidationError(
                        exc.reason,
                        attempts=attempt,
                        input_tokens=cumulative_in,
                        output_tokens=cumulative_out,
                    ) from exc

                msgs = msgs + [
                    UnifiedMessage(role="assistant", content=text or "(empty)"),
                    UnifiedMessage(
                        role="user",
                        content=_build_retry_message(
                            reason=exc.reason,
                            hint=exc.hint,
                            override=retry_directive,
                        ),
                    ),
                ]
                self._tracer.emit("validation_retry", phase=phase, attempt=attempt)
                continue

            return CallResult(
                response=response,
                text=text,
                parsed=parsed,
                provider_used=provider.model_id(),
                fallback_depth=fallback_depth,
                attempts=attempt,
                input_tokens=cumulative_in,
                output_tokens=cumulative_out,
            )


# Call-support helpers (``_repr_provider_ref``, ``_ms_since``,
# ``_build_retry_message``, ``_extract_text``, ``_usage_tokens``,
# ``_resolve_provider``) now live in ``app.services.llm._call_support`` and are
# imported under the same private names at the top of this module so both the
# streaming and non-streaming paths share one implementation.
