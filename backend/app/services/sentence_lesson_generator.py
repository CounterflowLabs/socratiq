"""SentenceLessonGenerator — a SOURCE-LESS block-based lesson generator.

The sentence→course path starts from a single one-sentence prompt, so the
frozen outline carries no ``source_chunk_indices`` — there is no transcript,
PDF, or reading material to summarize. This generator therefore produces a
lesson from the *outline alone* (section title + knowledge points), drawing on
the LLM's own topic knowledge. It is the deliberate opposite of
:class:`app.services.lesson_generator.LessonGenerator`, which compresses
provided source chunks.

It still emits the SAME block-based ``LessonContent`` shape (intro_card / prose
/ diagram / code_example / concept_relation / practice_trigger / recap /
next_step) and reuses ``LessonGenerator``'s battle-tested JSON parsing +
block-sanitization + AgentRuntime validated-retry machinery, so downstream
rendering and persistence are unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.models.lesson import LessonContent
from app.prompt_template import load_prompt
from app.services.lesson_generator import (
    _ALLOWED_BLOCK_TYPES,
    LessonGenerationError,
    _LessonGenError,
    _enforce_verified_urls,
    _parse_lesson_json,
)
from app.services.llm.base import LLMError, LLMProvider, UnifiedMessage
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    ValidationFailed,
)
from app.services.llm.token_budget import lesson_max_output_tokens

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(
    Path(__file__).parent / "prompts" / "sentence_lesson_generation.md"
)

_RETRY_DIRECTIVE = (
    "IMPORTANT: your previous response failed to parse as JSON. "
    "Reply with ONLY a single valid JSON object. Escape every newline as "
    "`\\n` and every double-quote as `\\\"` inside string values. The very "
    "last character of your response must be `}`. Keep the lesson short — "
    "4 to 6 blocks is plenty."
)


class SentenceLessonGenerator:
    """Generate a block-based lesson for one outline section without any source.

    Mirrors :class:`LessonGenerator`'s validator/retry contract but takes its
    content brief from the outline (``section_title`` + ``knowledge_points``)
    rather than from source chunks.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._runtime = AgentRuntime()
        # Provider is fixed for the generator's lifetime; resolve the output
        # budget once. (No input budget needed — there is no source payload to
        # truncate, only a short outline brief.)
        self._max_output_tokens = lesson_max_output_tokens(provider)

    async def generate(
        self,
        *,
        section_title: str,
        knowledge_points: list[str],
        difficulty: int,
        target_language: str,
        previous_section_title: str | None = None,
        next_section_title: str | None = None,
    ) -> LessonContent:
        """Produce a ``LessonContent`` for one section from the outline alone.

        Args:
            section_title: The frozen section title to teach.
            knowledge_points: The points this section must cover (may be empty;
                the model then teaches the title topic broadly).
            difficulty: 1 (easiest) – 5 (hardest); calibrates depth.
            target_language: Language for all natural-language fields.
            previous_section_title: Prior section title, for continuity.
            next_section_title: Next section title, previewed in ``next_step``.

        Returns:
            A validated ``LessonContent`` with a non-empty ``blocks`` array.

        Raises:
            LessonGenerationError: generation gave up after one corrective
                retry (so the caller can mark this section errored rather than
                emit a fake lesson).
        """
        kp_lines = (
            "\n".join(f"- {kp}" for kp in knowledge_points if str(kp).strip())
            or "- (no explicit knowledge points; teach the title topic broadly)"
        )
        prompt_text = _PROMPT.render(
            section_title=section_title,
            target_language=target_language,
            difficulty=str(difficulty),
            knowledge_points=kp_lines,
            previous_section_title=previous_section_title or "",
            next_section_title=next_section_title or "",
        )

        try:
            result = await self._runtime.call(
                [UnifiedMessage(role="user", content=prompt_text)],
                primary=self._provider,
                # Same-provider retry on transport error; the directive is only
                # appended on validator failures, so a network blip retries
                # against the original prompt.
                fallbacks=[self._provider],
                max_tokens=self._max_output_tokens,
                temperature=0.4,
                phase="sentence_lesson_generator.generate",
                validator=lambda text: self._validate_lesson(text, section_title),
                max_validation_retries=1,
                retry_directive=_RETRY_DIRECTIVE,
            )
        except LLMValidationError as exc:
            logger.error(
                "Sentence lesson generation failed after retry for '%s': %s",
                section_title,
                exc,
            )
            raise LessonGenerationError(str(exc)) from exc
        except LLMError as exc:
            logger.error(
                "Sentence lesson generation failed (transport) for '%s': %s",
                section_title,
                exc,
            )
            raise LessonGenerationError(str(exc)) from exc

        content = result.parsed
        # Source-less path has no vetted supplements, so no further_reading url
        # may survive: every reference becomes name-only (enforces the prompt's
        # "always leave url empty" rule deterministically).
        _enforce_verified_urls(content, set())
        return content  # LessonContent

    def _validate_lesson(self, text: str, section_title: str) -> LessonContent:
        """AgentRuntime validator: parse JSON + build a sanitized LessonContent.

        Raises ``ValidationFailed`` on JSON parse failure or on the
        valid-JSON-but-no-usable-blocks case so the runtime issues a single
        corrective retry with ``_RETRY_DIRECTIVE``.
        """
        try:
            data = _parse_lesson_json(text)
        except _LessonGenError as exc:
            raise ValidationFailed(
                f"json_parse_failed: {exc}",
                hint="Reply with ONLY a single valid JSON object.",
            ) from exc
        try:
            return self._build_content(data, section_title)
        except _LessonGenError as exc:
            raise ValidationFailed(
                f"no_usable_blocks: {exc}",
                hint="Include at least one block whose `type` is one of the allowed block types.",
            ) from exc

    def _build_content(self, data: dict, section_title: str) -> LessonContent:
        """Fill defaults + drop bogus block types, mirroring LessonGenerator."""
        if not data.get("title"):
            data["title"] = section_title
        if "summary" not in data:
            data["summary"] = ""
        raw_blocks = data.get("blocks") or []
        cleaned: list[dict] = []
        for blk in raw_blocks:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") not in _ALLOWED_BLOCK_TYPES:
                continue
            if blk.get("type") == "further_reading":
                refs = [
                    r for r in (blk.get("references") or [])
                    if isinstance(r, dict) and str(r.get("title") or "").strip()
                ]
                if not refs:
                    continue
                blk["references"] = refs
            cleaned.append(blk)
        if not cleaned:
            raise _LessonGenError("no usable blocks in response")
        data["blocks"] = cleaned
        return LessonContent(**data)
