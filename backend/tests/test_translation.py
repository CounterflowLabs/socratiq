"""Tests for translation service."""

import pytest
from unittest.mock import AsyncMock

from app.services.translation import TranslationService
from app.services.llm.base import LLMResponse, ContentBlock


class TestTranslationService:
    @pytest.mark.asyncio
    async def test_translate_text(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text="这是一个测试翻译")],
            model="mock",
        )
        service = TranslationService(mock_provider)
        result = await service.translate_text("This is a test translation", "zh")
        assert result == "这是一个测试翻译"

    @pytest.mark.asyncio
    async def test_translate_failure_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.side_effect = Exception("LLM error")
        service = TranslationService(mock_provider)
        result = await service.translate_text("Hello", "zh")
        assert result is None

    def test_estimate_tokens(self):
        service = TranslationService(AsyncMock())
        tokens = service.estimate_tokens(["Hello world", "Test text"], "zh")
        assert tokens > 0

    @pytest.mark.asyncio
    async def test_translate_text_empty_content_returns_none(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[],
            model="mock",
        )
        service = TranslationService(mock_provider)
        result = await service.translate_text("Hello", "zh")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_text_known_lang_names(self):
        """Provider is called with the correct language name in the prompt."""
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text="こんにちは")],
            model="mock",
        )
        service = TranslationService(mock_provider)
        result = await service.translate_text("Hello", "ja")
        assert result == "こんにちは"
        call_kwargs = mock_provider.chat.call_args
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
        # Check that "Japanese" appears in the message content
        content_str = messages[0].content if isinstance(messages[0].content, str) else str(messages[0].content)
        assert "Japanese" in content_str

    def test_estimate_tokens_scales_with_input(self):
        service = TranslationService(AsyncMock())
        short = service.estimate_tokens(["Hi"], "zh")
        long = service.estimate_tokens(["Hello world, this is a much longer text to translate"], "zh")
        assert long > short
