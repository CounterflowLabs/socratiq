"""LessonGenerator — converts subtitle chunks into a block-based lesson."""

import json
import logging
import re
from pathlib import Path

from app.models.lesson import LessonContent
from app.prompt_template import load_prompt
from app.services.llm.base import LLMProvider, UnifiedMessage

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
}


class LessonGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate(
        self,
        subtitle_chunks: list[str],
        video_title: str,
        target_language: str,
        user_directive: str = "",
        goal: str | None = None,
    ) -> LessonContent:
        """Convert subtitle chunks into a block-based lesson."""
        subtitles = "\n\n".join(subtitle_chunks)
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""

        prompt_text = _PROMPT.render(
            title=video_title,
            target_language=target_language,
            subtitles=subtitles[:8000],
            user_directive=user_directive,
        ) + goal_prompt

        # First attempt — any LLM error (timeout, network, parse failure) drops
        # us into the retry path; a second failure raises so the caller can
        # mark the section as errored rather than receive a fake lesson.
        try:
            data = await self._attempt(prompt_text)
            return self._build_content(data, video_title)
        except Exception as first_err:  # noqa: BLE001
            logger.warning(
                "Lesson generation first attempt failed (%s); retrying with stricter directive",
                first_err,
            )

        retry_prompt = (
            prompt_text
            + "\n\nIMPORTANT: your previous response failed to parse as JSON. "
            "Reply with ONLY a single valid JSON object. Escape every newline as "
            "`\\n` and every double-quote as `\\\"` inside string values. The very "
            "last character of your response must be `}`. Keep the lesson short — "
            "4 to 6 blocks is plenty."
        )
        try:
            data = await self._attempt(retry_prompt)
            return self._build_content(data, video_title)
        except Exception as second_err:  # noqa: BLE001
            logger.error("Lesson generation failed after retry: %s", second_err)
            raise LessonGenerationError(str(second_err)) from second_err

    async def _attempt(self, prompt_text: str) -> dict:
        response = await self._provider.chat(
            messages=[UnifiedMessage(role="user", content=prompt_text)],
            max_tokens=4000,
            temperature=0.3,
        )
        text = response.content[0].text if response.content else ""
        return _parse_lesson_json(text)

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
