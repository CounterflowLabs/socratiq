"""Unit tests for app.services.llm.token_budget."""

from unittest.mock import MagicMock

import pytest

from app.services.llm.token_budget import (
    DEFAULT_LESSON_MAX_OUTPUT_TOKENS,
    DEFAULT_PROMPT_OVERHEAD_TOKENS,
    _INPUT_SWEET_SPOT_TOKENS,
    context_window_tokens,
    count_tokens,
    lesson_input_token_budget,
    lesson_max_output_tokens,
    truncate_to_tokens,
)


def _provider_with_model(
    model_id: str, *, context_window: int | None = None
) -> MagicMock:
    """Lightweight provider double — only .model_id() needs to behave.

    When ``context_window`` is given, stamp it onto ``_context_window`` to
    mimic what :meth:`ModelRouter._create_provider` does for a model whose
    config declares an admin context window. Left unstamped (``None``) the
    double has no such attribute, so budgeting falls back to the table.
    """
    # spec=[] keeps ``getattr(p, "_context_window", None)`` returning the
    # default (None) when we don't stamp it — a bare MagicMock would auto-vivify
    # the attribute as a child mock and defeat the no-op path under test.
    p = MagicMock(spec=["model_id"])
    p.model_id = MagicMock(return_value=model_id)
    if context_window is not None:
        p._context_window = context_window
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

    def test_custom_named_cloud_variant_matches_family_prefix(self):
        # The regression that truncated dense lessons: a custom DeepSeek model
        # id not in the exact table must NOT collapse to the small fallback.
        assert context_window_tokens("deepseek-v4-flash") == 64_000
        # Even an unlisted deepseek-v* / chat variant inherits the family window.
        assert context_window_tokens("deepseek-v9-turbo-preview") == 64_000
        assert context_window_tokens("gpt-4o-2099-99-99") == 128_000
        assert context_window_tokens("claude-7-haiku-future") == 200_000

    def test_small_local_family_is_not_over_budgeted(self):
        # Local/small families are deliberately NOT prefix-matched: an unlisted
        # small model keeps the conservative fallback rather than being guessed
        # large (which would overflow its real window).
        assert context_window_tokens("llama-tiny-1b-custom") == context_window_tokens(
            "totally-made-up-model-99"
        )
        assert context_window_tokens("mistral-small-custom") == context_window_tokens(
            "totally-made-up-model-99"
        )


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


# --- provider-carried (admin-configured) context window --------------------


class TestProviderConfiguredContextWindow:
    """A window stamped onto the provider (from the DB model config) wins."""

    def test_configured_window_drives_budget_over_table(self):
        # Model id is unknown to the table (would fall back to 8192 → tiny
        # budget). A configured 64k window must override that and let the
        # formula produce the sweet-spot-capped 12k instead.
        provider = _provider_with_model(
            "totally-unknown-model-99", context_window=64_000
        )
        budget = lesson_input_token_budget(provider)
        assert budget == _INPUT_SWEET_SPOT_TOKENS  # 12_000

    def test_configured_window_below_sweet_spot_uses_formula(self):
        # A small declared window drives the subtractive formula directly:
        # 20_000 - 4000 (fallback max_output) - 1500 overhead = 14_500, then
        # capped by the 12k sweet spot. Pick a window low enough that the
        # formula (not the cap) wins to prove the configured value is used.
        provider = _provider_with_model("mystery-model", context_window=10_000)
        budget = lesson_input_token_budget(provider)
        expected = (
            10_000
            - DEFAULT_LESSON_MAX_OUTPUT_TOKENS
            - DEFAULT_PROMPT_OVERHEAD_TOKENS
        )
        assert budget == expected
        assert budget < _INPUT_SWEET_SPOT_TOKENS

    def test_configured_window_overrides_known_table_entry(self):
        # Even when the model IS in the table, an explicit config wins. Use a
        # tiny window so the result is unmistakably driven by the config and
        # not the table's 200k (which would hit the 12k cap).
        provider = _provider_with_model(
            "claude-3-5-sonnet-20241022", context_window=6_000
        )
        budget = lesson_input_token_budget(provider, max_output_tokens=1_000)
        # 6000 - 1000 - 1500 = 3500, well under the table-driven 12k cap.
        assert budget == 6_000 - 1_000 - DEFAULT_PROMPT_OVERHEAD_TOKENS
        assert budget < _INPUT_SWEET_SPOT_TOKENS

    def test_no_configured_window_is_a_noop(self):
        # Without a stamped window, behavior is identical to the table-only
        # path — the regression guard for unconfigured deployments.
        model_id = "totally-unknown"
        with_attr_absent = lesson_input_token_budget(
            _provider_with_model(model_id)
        )
        table_only = (
            context_window_tokens(model_id)
            - DEFAULT_LESSON_MAX_OUTPUT_TOKENS
            - DEFAULT_PROMPT_OVERHEAD_TOKENS
        )
        assert with_attr_absent == table_only

    def test_nonpositive_configured_window_is_ignored(self):
        # A zero / negative configured window is treated as "unset" so a bad
        # admin value can't drive the budget below its safe table fallback.
        bad = _provider_with_model("totally-unknown", context_window=0)
        good = _provider_with_model("totally-unknown")
        assert lesson_input_token_budget(bad) == lesson_input_token_budget(good)


# --- lesson_max_output_tokens ---------------------------------------------


class TestLessonMaxOutputTokens:
    def test_frontier_models_get_8k(self):
        for model in [
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-latest",
            "claude-sonnet-4-20250514",
            "gpt-4o",
            # DeepSeek bumped to 8k output so dense lessons aren't truncated.
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v4-flash",
        ]:
            assert lesson_max_output_tokens(_provider_with_model(model)) == 8_000, model

    def test_mid_tier_models_get_6k(self):
        for model in [
            "claude-3-5-haiku-latest",
            "gpt-4o-mini",
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
