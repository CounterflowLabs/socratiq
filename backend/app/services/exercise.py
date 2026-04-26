"""Exercise generation and evaluation service."""

import json
import logging
from pathlib import Path

from app.prompt_template import load_prompt
from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_GENERATION_PROMPT = load_prompt(_PROMPTS_DIR / "exercise_generation.md")
_EVALUATION_PROMPT = load_prompt(_PROMPTS_DIR / "exercise_evaluation.md")


class ExerciseService:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate_from_content(
        self,
        content: str,
        count: int = 3,
        types: list[str] | None = None,
        target_language: str = "zh-CN",
    ) -> list[dict]:
        type_str = ", ".join(types or ["mcq", "open"])
        prompt = _GENERATION_PROMPT.render(
            count=count,
            content=content[:3000],
            types=type_str,
            target_language=target_language,
        )

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(role="user", content=prompt)],
                max_tokens=2000, temperature=0.7,
            )
            text = response.content[0].text if response.content else "[]"
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            logger.error(f"Exercise generation failed: {e}")
            return []

    async def evaluate_submission(
        self,
        question: str,
        answer: str,
        correct_answer: str,
        exercise_type: str,
        target_language: str = "zh-CN",
    ) -> dict:
        if exercise_type == "mcq":
            is_correct = answer.strip().lower() == correct_answer.strip().lower()
            return {
                "score": 100.0 if is_correct else 0.0,
                "feedback": "正确！" if is_correct else f"正确答案是：{correct_answer}",
            }

        prompt = _EVALUATION_PROMPT.render(
            question=question,
            correct_answer=correct_answer,
            answer=answer,
            target_language=target_language,
        )

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(role="user", content=prompt)],
                max_tokens=500, temperature=0.3,
            )
            text = response.content[0].text if response.content else '{}'
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            return json.loads(text)
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            return {"score": None, "feedback": "评分失败，请稍后重试。"}
