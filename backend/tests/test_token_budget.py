"""Unit tests for app.services.llm.token_budget."""

from unittest.mock import MagicMock

import pytest

from app.services.llm.token_budget import (
    DEFAULT_LESSON_MAX_OUTPUT_TOKENS,
    DEFAULT_PROMPT_OVERHEAD_TOKENS,
    context_window_tokens,
    count_tokens,
    lesson_input_token_budget,
    lesson_max_output_tokens,
    truncate_to_tokens,
)


def _provider_with_model(model_id: str) -> MagicMock:
    """Lightweight provider double — only .model_id() needs to behave."""
    p = MagicMock()
    p.model_id = MagicMock(return_value=model_id)
    return p


# --- count_tokens ----------------------------------------------------------


class TestCountTokens:
    def test_empty_string_is_zero(self):
        assert count_tokens("") == 0

    def test_short_english_is_a_few_tokens(self):
        # tiktoken cl100k_base is deterministic; the exact count just needs
        # to be in a sane range — not 0, not absurdly large.
        n = count_tokens("hello world")
        assert 1 <= n <= 4

    def test_handles_chinese_input(self):
        # cl100k_base tokenizes CJK to roughly 1 token per character (some
        # common bigrams merge to <1). Just assert it returns something
        # reasonable — not zero, not absurdly high.
        cn = count_tokens("中文测试一二三四五")  # 9 chars
        assert 4 <= cn <= 20

    def test_handles_special_tokens_as_plain_text(self):
        # disallowed_special=() means strings like <|endoftext|> are tokenized
        # as plain text instead of raising.
        n = count_tokens("hello <|endoftext|> world")
        assert n > 0  # didn't raise


# --- truncate_to_tokens ----------------------------------------------------


class TestTruncateToTokens:
    def test_short_input_returns_unchanged(self):
        text = "hello world"
        assert truncate_to_tokens(text, 100) == text

    def test_long_input_is_cut_to_at_most_max_tokens(self):
        text = "hello world " * 200  # well over 10 tokens
        cut = truncate_to_tokens(text, 5)
        assert count_tokens(cut) <= 5
        assert len(cut) < len(text)

    def test_zero_max_returns_empty(self):
        assert truncate_to_tokens("anything", 0) == ""

    def test_negative_max_returns_empty(self):
        assert truncate_to_tokens("anything", -1) == ""

    def test_empty_text_returns_empty(self):
        assert truncate_to_tokens("", 100) == ""


# --- context_window_tokens -------------------------------------------------


class TestContextWindow:
    def test_known_anthropic_model(self):
        assert context_window_tokens("claude-3-5-sonnet-20241022") == 200_000

    def test_known_openai_model(self):
        assert context_window_tokens("gpt-4o") == 128_000

    def test_unknown_model_uses_fallback(self):
        # Fallback is conservative — exact value is an implementation
        # choice; we just assert it's reasonable.
        v = context_window_tokens("totally-made-up-model-99")
        assert 1024 <= v <= 32_768


# --- lesson_input_token_budget ---------------------------------------------


class TestLessonInputTokenBudget:
    def test_long_context_provider_hits_sweet_spot_cap(self):
        # Claude 200k - 8000 - 1500 = 190,500, capped to sweet spot 12k.
        budget = lesson_input_token_budget(
            _provider_with_model("claude-3-5-sonnet-20241022"),
        )
        assert budget == 12_000

    def test_small_context_provider_is_below_sweet_spot(self):
        # Unknown model → fallback context 8192, fallback max_output 4000.
        # 8192 - 4000 - 1500 = 2692, well below sweet spot.
        budget = lesson_input_token_budget(
            _provider_with_model("totally-unknown"),
        )
        assert budget == 8192 - DEFAULT_LESSON_MAX_OUTPUT_TOKENS - DEFAULT_PROMPT_OVERHEAD_TOKENS

    def test_custom_max_output_changes_budget(self):
        # Use a small-context provider so the formula (not the sweet-spot
        # cap) drives the result. Explicit max_output overrides the
        # provider-aware auto-derivation.
        provider = _provider_with_model("totally-unknown")
        normal = lesson_input_token_budget(provider, max_output_tokens=1000)
        bigger_output = lesson_input_token_budget(provider, max_output_tokens=4000)
        assert bigger_output < normal
        assert (normal - bigger_output) == 3000

    def test_auto_derives_max_output_when_omitted(self):
        # Sonnet should auto-pick its provider-aware 8000 max_output.
        # Same call with the value passed explicitly should match.
        provider = _provider_with_model("claude-3-5-sonnet-20241022")
        auto = lesson_input_token_budget(provider)
        explicit = lesson_input_token_budget(provider, max_output_tokens=8000)
        assert auto == explicit

    def test_budget_has_a_floor(self):
        # Even with absurd overhead the result clamps up to the floor so
        # callers never receive 0 or negative budgets.
        provider = _provider_with_model("totally-unknown")
        budget = lesson_input_token_budget(
            provider,
            max_output_tokens=8000,
            prompt_overhead_tokens=8000,
        )
        assert budget >= 512

    def test_gpt4o_hits_sweet_spot_cap(self):
        # 128k context still capped at 12k by sweet spot.
        budget = lesson_input_token_budget(_provider_with_model("gpt-4o"))
        assert budget == 12_000


# --- lesson_max_output_tokens ---------------------------------------------


class TestLessonMaxOutputTokens:
    def test_frontier_models_get_8k(self):
        for model in [
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-latest",
            "claude-sonnet-4-20250514",
            "gpt-4o",
        ]:
            assert lesson_max_output_tokens(_provider_with_model(model)) == 8_000, model

    def test_mid_tier_models_get_6k(self):
        for model in [
            "claude-3-5-haiku-latest",
            "gpt-4o-mini",
            "deepseek-chat",
            "qwen-max",
        ]:
            assert lesson_max_output_tokens(_provider_with_model(model)) == 6_000, model

    def test_small_local_models_stay_at_4k(self):
        for model in ["llama3.1:8b", "qwen2.5:7b", "llama-3.1-8b-instant"]:
            assert lesson_max_output_tokens(_provider_with_model(model)) == 4_000, model

    def test_unknown_model_falls_back_to_default(self):
        assert lesson_max_output_tokens(
            _provider_with_model("totally-unknown-model-99")
        ) == DEFAULT_LESSON_MAX_OUTPUT_TOKENS
