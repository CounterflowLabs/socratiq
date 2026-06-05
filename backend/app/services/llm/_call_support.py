"""Shared call-support primitives for LLM invocation.

Both the non-streaming :class:`~app.services.llm.runtime.AgentRuntime` and the
streaming ``RouterLLMClient`` in ``app.agentcore.llm`` need the same building
blocks: resolving a provider reference (concrete provider or ``TaskType`` via
the router), formatting trace labels, building corrective-retry messages, and
pulling text/token usage out of a response. Centralizing them here keeps the
fallback/validation/accounting logic identical across the streaming and
non-streaming paths instead of duplicating it.

This module is intentionally dependency-light (only ``base`` + ``router``) so
it can be imported from either side without a cycle.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.router import ModelRouter, TaskType

if TYPE_CHECKING:
    from app.services.llm.base import LLMResponse


ProviderRef = LLMProvider | TaskType
"""Either a concrete provider, or a ``TaskType`` resolved via ``ModelRouter``."""


async def resolve_provider(
    ref: ProviderRef, router: ModelRouter | None
) -> LLMProvider:
    """Resolve a provider reference to a concrete :class:`LLMProvider`.

    A ``TaskType`` is looked up through ``router``; anything else is assumed to
    already be a provider (duck-typed so ``AsyncMock`` works in tests without a
    ``spec=LLMProvider`` ceremony — the actual ``await ref.chat(...)`` will
    raise later if it isn't really a provider).
    """
    if isinstance(ref, TaskType):
        if router is None:
            raise LLMError(
                f"resolve_provider needs a ModelRouter to resolve TaskType.{ref.name}"
            )
        return await router.get_provider(ref)
    return ref  # type: ignore[return-value]


def repr_provider_ref(ref: ProviderRef) -> str:
    """Stable, log-friendly label for a provider reference."""
    if isinstance(ref, TaskType):
        return f"task:{ref.value}"
    if isinstance(ref, LLMProvider):
        try:
            return f"provider:{ref.model_id()}"
        except Exception:  # noqa: BLE001
            return f"provider:{type(ref).__name__}"
    return repr(ref)


def ms_since(started: float) -> float:
    """Elapsed milliseconds since a ``time.perf_counter()`` mark."""
    return (time.perf_counter() - started) * 1000.0


def build_retry_message(
    *, reason: str, hint: str | None, override: str | None
) -> str:
    """Construct the corrective user message appended after a failed validation.

    ``override`` (a caller-supplied ``retry_directive``) wins verbatim; else a
    generated message that surfaces ``reason`` plus an optional ``hint``.
    """
    if override:
        return override
    base = (
        "Your previous response did not pass validation: "
        f"{reason}. Please respond again, this time fixing the issue."
    )
    if hint:
        return f"{base}\n\nHint: {hint}"
    return base


def extract_text(response: "LLMResponse") -> str:
    """Concatenate the text content blocks of a response."""
    return "".join(b.text or "" for b in response.content if b.type == "text")


def usage_tokens(response: "LLMResponse") -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)``, defaulting to 0 when absent."""
    if response.usage is None:
        return 0, 0
    return response.usage.input_tokens, response.usage.output_tokens
