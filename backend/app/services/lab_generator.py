"""LabGenerator — creates code labs from lesson code snippets."""

import json
import logging
from pathlib import Path

from app.models.lesson import CodeSnippet
from app.prompt_template import load_prompt
from app.services.llm.base import LLMError, LLMProvider, UnifiedMessage
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    ValidationFailed,
)

logger = logging.getLogger(__name__)

RUN_TEMPLATES = {
    "python": "```bash\ncd {lab_dir}\npip install -r requirements.txt  # if exists\npython -m pytest tests/ -v\n```",
    "go": "```bash\ncd {lab_dir}\ngo test ./... -v\n```",
    "javascript": "```bash\ncd {lab_dir}\nnpm install\nnpm test\n```",
    "typescript": "```bash\ncd {lab_dir}\nnpm install\nnpm test\n```",
}

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "lab_generation.md")


class LabGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider
        self._runtime = AgentRuntime()

    async def generate(
        self,
        code_snippets: list[CodeSnippet],
        lesson_context: str,
        language: str,
        target_language: str,
        user_directive: str = "",
        goal: str | None = None,
    ) -> dict | None:
        """Generate a lab from code snippets. Returns None if no code or low confidence."""
        if not code_snippets:
            return None

        snippets_text = "\n\n".join(
            f"```{s.language}\n{s.code}\n```\nContext: {s.context}" for s in code_snippets
        )
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""
        prompt_text = _PROMPT.render(
            snippets=snippets_text,
            context=lesson_context[:3000],
            language=language,
            target_language=target_language,
            user_directive=user_directive,
        ) + goal_prompt

        # JSON parse runs inside the validator so the runtime can give us one
        # corrective retry. Any other failure (provider down, validator
        # exhausted) degrades to None so the upstream lab pipeline simply
        # skips this lesson — matches pre-runtime behavior.
        try:
            result = await self._runtime.call(
                [UnifiedMessage(role="user", content=prompt_text)],
                primary=self._provider,
                max_tokens=4000,
                temperature=0.3,
                phase="lab_generator.generate",
                validator=_parse_lab_json,
            )
        except (LLMValidationError, LLMError) as e:
            logger.error(f"Lab generation failed: {e}")
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"Lab generation failed: {e}")
            return None

        data: dict = result.parsed

        # Confidence threshold is a quality decision, not a parse failure —
        # keep it out of the validator so the runtime doesn't waste a retry.
        if data.get("confidence", 0) < 0.3:
            logger.info(f"Lab confidence too low ({data.get('confidence')}), skipping")
            return None

        if not data.get("run_instructions"):
            template = RUN_TEMPLATES.get(language, RUN_TEMPLATES["python"])
            data["run_instructions"] = template.format(
                lab_dir=f"lab_{data.get('title', 'exercise').lower().replace(' ', '_')}"
            )

        return data


def _parse_lab_json(response_text: str) -> dict:
    """Validator: strip fences, parse JSON, raise ValidationFailed on bad input."""
    text = response_text or "{}"
    stripped = text.strip()
    if stripped.startswith("```"):
        text = stripped.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(
            f"invalid_json: {exc}",
            hint="Reply with a single JSON object only — no prose, no fences.",
        ) from exc

    if not isinstance(data, dict):
        raise ValidationFailed(
            "response was valid JSON but not an object",
            hint="Wrap the lab fields in a top-level `{...}` object.",
        )
    return data
