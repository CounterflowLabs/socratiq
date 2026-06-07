"""Token budget computation — context-window-aware, tokenizer-approximated.

Strategy:
  - tiktoken cl100k_base as a universal token approximator. Errors stay
    under ~15% even for Chinese / non-OpenAI tokenizers, which is well
    within the safety margin baked into the budget formula below.
  - Per-model context windows live in a hand-maintained table that
    mirrors LiteLLM's model_prices_and_context_window.json layout.
    Unknown models fall back to a conservative 8k window.
  - Sweet-spot cap (12k input tokens) regardless of how big the context
    is — long-context attention degrades past that range
    (Liu et al. 2023, "Lost in the Middle"), so we don't blindly fill
    a 200k context just because we can.
  - Subtract reserved overhead for prompt template + max_output_tokens
    so the remaining budget is what the caller can actually use for
    user content.
"""

from __future__ import annotations

import tiktoken

from app.services.llm.base import LLMProvider


# Default max_output for unknown models. Conservative — see _MODEL_OUTPUT_TOKENS
# for per-model overrides. Changed callers should prefer the provider-aware
# helper ``lesson_max_output_tokens()`` over reading this constant directly.
DEFAULT_LESSON_MAX_OUTPUT_TOKENS = 4000

DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500

# Long-context attention degrades past ~12k tokens for most models.
_INPUT_SWEET_SPOT_TOKENS = 12_000

# Floor for any computed budget so we never return absurdly small values.
_MIN_BUDGET_TOKENS = 512

# Conservative fallback for models we don't have in the table.
_FALLBACK_CONTEXT = 8_192


# Mirrors LiteLLM's model_prices_and_context_window.json (input context only).
# Maintained manually for the providers we route through.
# Per-model max_tokens for lesson generation. Tuned to where each model
# stays coherent on long structured-JSON output:
#   - Frontier models (Claude Sonnet/Opus, GPT-4o) hold 8k easily.
#   - Mid-tier (Haiku, GPT-4o-mini, DeepSeek, Qwen-max) settle around 6k.
#   - Small / older models stay at 4k to avoid drift past their sweet spot.
# Note: bigger here doesn't mean longer lessons — the prompt still targets
# 4-8 blocks. This just removes the artificial cap on dense source material.
_MODEL_OUTPUT_TOKENS: dict[str, int] = {
    # Anthropic — large stable output budget
    "claude-3-5-sonnet-20241022": 8_000,
    "claude-3-5-sonnet-latest":   8_000,
    "claude-3-5-haiku-20241022":  6_000,
    "claude-3-5-haiku-latest":    6_000,
    "claude-3-opus-20240229":     8_000,
    "claude-3-opus-latest":       8_000,
    "claude-sonnet-4-20250514":   8_000,
    "claude-opus-4-20250514":     8_000,
    # OpenAI
    "gpt-4o":                     8_000,
    "gpt-4o-mini":                6_000,
    "gpt-4-turbo":                4_000,
    "gpt-4":                      4_000,
    "gpt-3.5-turbo":              4_000,
    "o1-preview":                 8_000,
    "o1-mini":                    6_000,
    # DeepSeek — 8k output headroom so dense, fully-developed lessons aren't
    # truncated (DeepSeek supports up to 8192 output tokens).
    "deepseek-chat":              8_000,
    "deepseek-reasoner":          8_000,
    "deepseek-v4-flash":          8_000,
    # Qwen
    "qwen-max":                   6_000,
    "qwen-plus":                  6_000,
    "qwen-turbo":                 4_000,
    "qwen2.5:7b":                 4_000,
    "qwen2.5:14b":                6_000,
    # Local / Llama via Ollama — be conservative on smaller variants
    "llama3.1:8b":                4_000,
    "llama3.1:70b":               6_000,
    "llama3.2:3b":                4_000,
    # Groq commonly-routed models
    "llama-3.1-70b-versatile":    6_000,
    "llama-3.1-8b-instant":       4_000,
}


_MODEL_CONTEXT_TOKENS: dict[str, int] = {
    # Anthropic
    "claude-3-5-sonnet-20241022":  200_000,
    "claude-3-5-sonnet-latest":    200_000,
    "claude-3-5-haiku-20241022":   200_000,
    "claude-3-5-haiku-latest":     200_000,
    "claude-3-opus-20240229":      200_000,
    "claude-3-opus-latest":        200_000,
    "claude-sonnet-4-20250514":    200_000,
    "claude-opus-4-20250514":      200_000,
    # OpenAI
    "gpt-4o":                      128_000,
    "gpt-4o-mini":                 128_000,
    "gpt-4-turbo":                 128_000,
    "gpt-4":                        32_768,
    "gpt-3.5-turbo":                16_385,
    "o1-preview":                  128_000,
    "o1-mini":                     128_000,
    # DeepSeek
    "deepseek-chat":                64_000,
    "deepseek-reasoner":            64_000,
    "deepseek-v4-flash":            64_000,
    # Qwen
    "qwen-max":                     32_000,
    "qwen-plus":                   131_000,
    "qwen-turbo":                1_000_000,
    "qwen2.5:7b":                   32_000,
    "qwen2.5:14b":                 128_000,
    # Local / Llama via Ollama
    "llama3.1:8b":                 128_000,
    "llama3.1:70b":                128_000,
    "llama3.2:3b":                 128_000,
    # Groq commonly-routed models
    "llama-3.1-70b-versatile":     128_000,
    "llama-3.1-8b-instant":        128_000,
}


# Single shared encoder. tiktoken's encoders are thread-safe and cheap to
# reuse, but instantiation walks a vocab file from disk so we avoid
# re-creating it per call.
_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens via tiktoken cl100k_base.

    Universal approximator with <15% error vs native tokenizers for the
    model families we route through. ``disallowed_special=()`` keeps
    user content with ``<|endoftext|>``-style strings from raising.
    """
    if not text:
        return 0
    return len(_ENCODER.encode(text, disallowed_special=()))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate ``text`` so it encodes to at most ``max_tokens`` tokens.

    Decoded output may end mid-word — token boundaries don't align with
    word boundaries. Callers that care about visible truncation should
    add their own ellipsis or trim to whitespace afterwards.
    """
    if max_tokens <= 0 or not text:
        return ""
    tokens = _ENCODER.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    return _ENCODER.decode(tokens[:max_tokens])


# Family-prefix fallback for the context window. An unlisted model whose id
# starts with one of these (case-insensitive) inherits the family's window, so
# a custom-named variant of a known cloud model (e.g. "deepseek-v4-flash", a
# renamed GPT-4o/Claude deployment) doesn't collapse to ``_FALLBACK_CONTEXT``
# and silently under-budget every lesson. Restricted to cloud families that are
# UNIFORMLY large-context — local/small families (llama, qwen-small, mistral)
# are intentionally absent so a genuinely small local model keeps the safe
# conservative fallback instead of being over-budgeted (which would overflow
# its real window). Checked in order; first prefix match wins.
_CONTEXT_FAMILY_PREFIXES: tuple[tuple[str, int], ...] = (
    ("claude", 200_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4.1", 1_000_000),
    ("o1", 128_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("deepseek-chat", 64_000),
    ("deepseek-reasoner", 64_000),
    ("deepseek-v", 64_000),
    ("gemini", 1_000_000),
)


def context_window_tokens(model_id: str) -> int:
    """Look up the input context window for ``model_id``.

    Resolution order: exact table → cloud-family prefix → ``_FALLBACK_CONTEXT``.
    The family-prefix step keeps custom-named variants of known large-context
    cloud models from collapsing to the conservative fallback and
    under-budgeting lessons (the failure that truncated dense sections). Public
    so tests and diagnostic tools can inspect the routing.
    """
    exact = _MODEL_CONTEXT_TOKENS.get(model_id)
    if exact is not None:
        return exact
    lowered = model_id.lower()
    for prefix, ctx in _CONTEXT_FAMILY_PREFIXES:
        if lowered.startswith(prefix):
            return ctx
    return _FALLBACK_CONTEXT


def _provider_context_window(provider: LLMProvider) -> int | None:
    """Return an admin-declared context window stamped onto ``provider``.

    The router stamps ``provider._context_window`` from the model config's
    ``context_window_tokens`` column when a deployment declares one (see
    :meth:`ModelRouter._create_provider`). This is the first-class, per-model
    source of truth: when present it overrides the hand-maintained table so a
    model id the table doesn't recognize no longer under-budgets lessons.

    Returns ``None`` when the provider carries no usable window (attribute
    absent, ``None``, or non-positive), in which case callers fall back to the
    table/family lookup — a strict no-op for unconfigured deployments.
    """
    window = getattr(provider, "_context_window", None)
    if isinstance(window, int) and window > 0:
        return window
    return None


def lesson_max_output_tokens(provider: LLMProvider) -> int:
    """Per-call max_tokens for lesson generation against ``provider``.

    Looks up ``provider.model_id()`` in :data:`_MODEL_OUTPUT_TOKENS` —
    bigger / more-capable models get a larger budget so dense source
    material doesn't hit an artificial cap, while smaller models stay
    at 4k to avoid late-output drift.

    Unknown models fall back to :data:`DEFAULT_LESSON_MAX_OUTPUT_TOKENS`.
    """
    return _MODEL_OUTPUT_TOKENS.get(
        provider.model_id(), DEFAULT_LESSON_MAX_OUTPUT_TOKENS,
    )


def lesson_input_token_budget(
    provider: LLMProvider,
    *,
    max_output_tokens: int | None = None,
    prompt_overhead_tokens: int = DEFAULT_PROMPT_OVERHEAD_TOKENS,
) -> int:
    """Maximum input tokens for one lesson_generator call against ``provider``.

    Computed as::

        budget = min(
            context_window(provider) - max_output_tokens - prompt_overhead,
            INPUT_SWEET_SPOT_TOKENS,
        )

    When ``max_output_tokens`` is ``None`` (the production default) it's
    auto-derived via :func:`lesson_max_output_tokens` against the same
    provider, keeping input + output budgets aligned. Tests can pass an
    explicit value to drive boundary cases.

    Context-window resolution order: an admin-declared window stamped onto the
    provider (``provider._context_window``, set by the router from the model
    config) → :func:`context_window_tokens` table/family lookup on
    ``provider.model_id()`` → conservative fallback. When the provider carries
    no configured window this is a strict no-op (identical to the old
    table-only behavior).

    The sweet-spot cap dominates for any modern long-context model and
    keeps single-call inputs in the range where the model's attention
    actually retains the content.
    """
    if max_output_tokens is None:
        max_output_tokens = lesson_max_output_tokens(provider)
    ctx = _provider_context_window(provider)
    if ctx is None:
        ctx = context_window_tokens(provider.model_id())
    raw = ctx - max_output_tokens - prompt_overhead_tokens
    return max(_MIN_BUDGET_TOKENS, min(raw, _INPUT_SWEET_SPOT_TOKENS))


__all__ = [
    "DEFAULT_LESSON_MAX_OUTPUT_TOKENS",
    "DEFAULT_PROMPT_OVERHEAD_TOKENS",
    "context_window_tokens",
    "count_tokens",
    "lesson_input_token_budget",
    "lesson_max_output_tokens",
    "truncate_to_tokens",
]
