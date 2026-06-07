"""LessonGenerator — converts subtitle chunks into a block-based lesson."""

import json
import logging
import re
from pathlib import Path

from app.models.lesson import LessonContent, LessonSourceChunk
from app.models.research import ResearchCard
from app.prompt_template import load_prompt
from app.services.llm.base import LLMError, LLMProvider, UnifiedMessage
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    ValidationFailed,
)
from app.services.llm.token_budget import (
    count_tokens,
    lesson_input_token_budget,
    lesson_max_output_tokens,
    truncate_to_tokens,
)

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "lesson_generation.md")

# Block types the model is allowed to emit. Anything else is dropped.
_ALLOWED_BLOCK_TYPES = {
    "intro_card",
    "prose",
    "diagram",
    "code_example",
    "concept_relation",
    "practice_trigger",
    "recap",
    "next_step",
    "further_reading",
}


_RETRY_DIRECTIVE = (
    "IMPORTANT: your previous response failed to parse as JSON. "
    "Reply with ONLY a single valid JSON object. Escape every newline as "
    "`\\n` and every double-quote as `\\\"` inside string values. Close every "
    "brace and bracket so the very last character of your response is `}`."
)


def _enforce_verified_urls(lesson: "LessonContent", allowed_urls: set[str]) -> None:
    """Drop any ``further_reading`` reference url that isn't a vetted supplement
    url. Prompt rules ask the model not to fabricate urls; this makes it a
    guarantee — unverified references survive as name-only (title kept)."""
    for block in lesson.blocks or []:
        if getattr(block, "type", None) != "further_reading":
            continue
        for ref in block.references or []:
            if ref.url and ref.url.strip() not in allowed_urls:
                ref.url = None


class LessonGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider
        self._runtime = AgentRuntime()
        # Both budgets resolved once per instance — provider is fixed for the
        # generator's lifetime. max_output is provider-aware (capable models
        # like Claude / GPT-4o get 8k for dense source; small models stay at
        # 4k to avoid late-output drift). Input budget is auto-derived against
        # the same provider so the two stay aligned.
        self._max_output_tokens = lesson_max_output_tokens(provider)
        self._input_token_budget = lesson_input_token_budget(provider)

    async def generate(
        self,
        subtitle_chunks: list[str],
        video_title: str,
        target_language: str,
        user_directive: str = "",
        goal: str | None = None,
        source_chunks: list[LessonSourceChunk] | None = None,
        research_cards: list[ResearchCard] | None = None,
        previous_section_title: str | None = None,
        next_section_title: str | None = None,
        previous_section_context: str | None = None,
    ) -> LessonContent:
        """Convert subtitle chunks into a block-based lesson."""
        source_format = "structured_json" if source_chunks else "plain_text"
        if source_chunks:
            source_payload = json.dumps(
                [chunk.model_dump(exclude_none=True) for chunk in source_chunks],
                ensure_ascii=False,
            )
        else:
            source_payload = "\n\n".join(subtitle_chunks)
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""

        # Defensive truncation. The upstream SectionPlanner is responsible
        # for keeping bucket sizes within budget; if we hit this branch it
        # means the planner emitted an oversized bucket, which should be
        # investigated rather than silently accepted.
        n_tokens = count_tokens(source_payload)
        if n_tokens > self._input_token_budget:
            logger.warning(
                "Lesson input %d tokens exceeds budget %d for model=%s; "
                "truncating tail. Upstream planner emitted oversized bucket.",
                n_tokens, self._input_token_budget, self._provider.model_id(),
            )
            source_payload = truncate_to_tokens(
                source_payload, self._input_token_budget
            )

        prompt_text = _PROMPT.render(
            title=video_title,
            target_language=target_language,
            source_format=source_format,
            source_chunks=source_payload,
            previous_section_title=previous_section_title or "",
            previous_section_context=previous_section_context or "",
            next_section_title=next_section_title or "",
            research_cards=json.dumps(
                [
                    card.model_dump(exclude_none=True)
                    for card in (research_cards or [])
                ],
                ensure_ascii=False,
            ),
            user_directive=user_directive,
        ) + goal_prompt

        # JSON parse + block filtering both happen inside the validator so a
        # bad first response triggers exactly one corrective retry against
        # the same provider. A second failure (validation or transport) is
        # surfaced as ``LessonGenerationError`` so the caller can mark the
        # section as errored rather than receive a fake lesson.
        try:
            result = await self._runtime.call(
                [UnifiedMessage(role="user", content=prompt_text)],
                primary=self._provider,
                # Same-provider retry on transport error; the directive only
                # gets appended on validator failures, so a network blip
                # retries with the original prompt — safer than the old
                # behavior which always lied to the model with a JSON-only
                # directive even when the cause was a timeout.
                fallbacks=[self._provider],
                max_tokens=self._max_output_tokens,
                temperature=0.3,
                phase="lesson_generator.generate",
                validator=lambda text: self._validate_lesson(text, video_title),
                max_validation_retries=1,
                retry_directive=_RETRY_DIRECTIVE,
            )
        except LLMValidationError as exc:
            logger.error("Lesson generation failed after retry: %s", exc)
            raise LessonGenerationError(str(exc)) from exc
        except LLMError as exc:
            logger.error("Lesson generation failed (transport): %s", exc)
            raise LessonGenerationError(str(exc)) from exc

        content: LessonContent = result.parsed
        # Code-enforce the anti-hallucination rule: keep a further_reading url
        # only when it's a vetted supplement url (the model is asked to do this,
        # but occasionally emits a remembered url for famous works — guaranteed
        # here so a guessed/fabricated link can never reach the learner).
        _enforce_verified_urls(
            content, {c.url.strip() for c in (research_cards or []) if c.url}
        )
        return content

    def _validate_lesson(self, text: str, video_title: str) -> LessonContent:
        """AgentRuntime validator: parse JSON + build LessonContent.

        Raises ``ValidationFailed`` on JSON parse failure or on the
        valid-JSON-but-no-usable-blocks case so the runtime issues a
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
            return self._build_content(data, video_title)
        except _LessonGenError as exc:
            raise ValidationFailed(
                f"no_usable_blocks: {exc}",
                hint="Include at least one block whose `type` is one of the allowed block types.",
            ) from exc

    def _build_content(self, data: dict, video_title: str) -> LessonContent:
        if not data.get("title"):
            data["title"] = video_title
        if "summary" not in data:
            data["summary"] = ""
        # Some small open-weights models add bogus block types or drop required
        # `type` fields. Sanitize before validation so a single bad block does
        # not nuke the entire lesson.
        raw_blocks = data.get("blocks") or []
        cleaned: list[dict] = []
        for blk in raw_blocks:
            if not isinstance(blk, dict):
                continue
            btype = blk.get("type")
            if btype not in _ALLOWED_BLOCK_TYPES:
                continue
            if btype == "further_reading":
                # Drop malformed references (a title is the one required field)
                # so one bad entry can't fail the whole lesson, and skip the
                # block entirely if nothing usable remains.
                refs = [
                    r for r in (blk.get("references") or [])
                    if isinstance(r, dict) and str(r.get("title") or "").strip()
                ]
                if not refs:
                    continue
                blk["references"] = refs
            cleaned.append(blk)
        if not cleaned:
            # A parse-succeeds-but-no-usable-blocks response gives the learner
            # a blank section. Treat it the same as a JSON failure so the
            # caller retries, and eventually falls back to a single prose
            # block of the raw transcript rather than nothing at all.
            raise _LessonGenError("no usable blocks in response")
        data["blocks"] = cleaned
        return LessonContent(**data)

class LessonGenerationError(Exception):
    """Raised when lesson generation gives up after retry.

    Public exception — callers (course_generator, lesson regeneration task)
    catch this to surface a per-section error to the user instead of writing
    a fake lesson.
    """


class _LessonGenError(Exception):
    """Raised when a single generation attempt fails to produce a usable dict."""


def _parse_lesson_json(text: str) -> dict:
    """Best-effort parse of an LLM response into a lesson dict.

    Handles:
    - ```` ```json ... ``` ```` fenced output
    - trailing prose after the closing brace
    - truncated output where the final block is incomplete
    """
    if not text:
        raise _LessonGenError("empty response")

    cleaned = _strip_fences(text)
    candidates = [cleaned]

    # If the model wrapped the JSON in chatter, fall back to the largest
    # top-level brace span.
    span = _extract_outermost_object(cleaned)
    if span and span != cleaned:
        candidates.append(span)

    # If that still fails, try repairing a truncated tail by chopping back to
    # the last complete block, then closing the object.
    repaired = _repair_truncated_json(span or cleaned)
    if repaired:
        candidates.append(repaired)

    last_err: Exception | None = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    raise _LessonGenError(str(last_err) if last_err else "unparseable JSON")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Drop opening fence and optional language tag, then drop the closing
        # fence if present.
        body = text[3:]
        if body.lower().startswith("json"):
            body = body[4:]
        body = body.lstrip("\r\n")
        if "```" in body:
            body = body.split("```", 1)[0]
        return body.strip()
    return text


def _extract_outermost_object(text: str) -> str | None:
    """Return the substring from the first `{` to the matching `}` (string-aware)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to salvage a truncated JSON object by chopping the tail.

    Strategy: locate the last `},` inside `"blocks": [...]`, treat that as
    the end of the final intact block, then close the `blocks` array and the
    enclosing object. This recovers the case where a small model ran out of
    tokens midway through emitting a block.
    """
    if not text or "blocks" not in text:
        return None
    blocks_idx = text.find('"blocks"')
    if blocks_idx == -1:
        return None
    array_open = text.find("[", blocks_idx)
    if array_open == -1:
        return None
    # Walk forward inside the array, tracking the end of the most recent
    # successfully-closed block object.
    depth = 0
    in_string = False
    escape = False
    last_close = -1
    for i in range(array_open, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_close = i
    if last_close == -1:
        return None
    head = text[: last_close + 1] + "]}"
    # The pre-blocks portion may still be missing trailing fields; we accept
    # the array-closed version and let json.loads validate.
    return head
