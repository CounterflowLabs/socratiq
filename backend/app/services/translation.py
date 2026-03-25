"""Subtitle translation service with caching."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)

_LANG_NAMES: dict[str, str] = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
}


class TranslationService:
    """Translates content chunks via LLM with DB-backed caching.

    Args:
        provider: LLM provider used for translation requests.
        db: Optional async DB session used for cache look-ups and writes.
    """

    def __init__(self, provider: LLMProvider, db: AsyncSession | None = None) -> None:
        self._provider = provider
        self._db = db

    async def translate_text(self, text: str, target_lang: str) -> str | None:
        """Translate a single text chunk via LLM.

        Args:
            text: Source text to translate.
            target_lang: BCP-47 language code of the target language.

        Returns:
            Translated text, or ``None`` on failure.
        """
        lang_name = _LANG_NAMES.get(target_lang, target_lang)

        try:
            response = await self._provider.chat(
                messages=[
                    UnifiedMessage(
                        role="user",
                        content=(
                            f"Translate the following text to {lang_name}. "
                            "Return ONLY the translation, no explanations:\n\n"
                            f"{text}"
                        ),
                    )
                ],
                max_tokens=len(text) * 3,
                temperature=0.3,
            )
            return response.content[0].text.strip() if response.content else None
        except Exception as exc:
            logger.error("Translation failed: %s", exc)
            return None

    @staticmethod
    def estimate_tokens(texts: list[str], target_lang: str) -> int:
        """Rough token estimate for a batch of translation requests.

        Args:
            texts: Source texts to be translated.
            target_lang: Target language code (affects output length estimate).

        Returns:
            Estimated total tokens (input + output).
        """
        total_chars = sum(len(t) for t in texts)
        # ~4 chars per token for English source
        input_tokens = total_chars // 4
        # Output may be longer (e.g. Chinese characters per token ratio differs)
        output_tokens = input_tokens * 2
        return input_tokens + output_tokens

    async def translate_section_chunks(
        self,
        chunks: list[dict],
        target_lang: str,
        user_id: UUID,
    ) -> list[dict]:
        """Translate a list of chunk dicts, using the cache where available.

        Args:
            chunks: List of ``{"id": UUID, "text": str}`` dicts.
            target_lang: Target language code.
            user_id: User ID for audit / cost logging.

        Returns:
            List of ``{"chunk_id": str, "translated_text": str | None}`` dicts
            in the same order as *chunks*.
        """
        from app.db.models.translation import Translation

        results: list[dict] = []

        for chunk in chunks:
            # --- cache look-up ---
            if self._db is not None:
                cached_row = await self._db.execute(
                    select(Translation).where(
                        Translation.chunk_id == chunk["id"],
                        Translation.target_lang == target_lang,
                    )
                )
                existing = cached_row.scalar_one_or_none()
                if existing:
                    results.append(
                        {
                            "chunk_id": str(chunk["id"]),
                            "translated_text": existing.translated_text,
                        }
                    )
                    continue

            # --- translate ---
            translated = await self.translate_text(chunk["text"], target_lang)

            # --- cache write ---
            if translated and self._db is not None:
                record = Translation(
                    chunk_id=chunk["id"],
                    target_lang=target_lang,
                    translated_text=translated,
                    model_used="light",
                )
                self._db.add(record)
                await self._db.flush()

            results.append(
                {
                    "chunk_id": str(chunk["id"]),
                    "translated_text": translated,
                }
            )

        return results
