"""Exercise generation and evaluation service."""

import json
import logging

from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)


class ExerciseService:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate_from_content(
        self, content: str, count: int = 3, types: list[str] | None = None,
    ) -> list[dict]:
        type_str = ", ".join(types or ["mcq", "open"])
        prompt = f"""Generate {count} exercises based on this learning content:

{content[:3000]}

Exercise types to include: {type_str}

For each exercise return:
- type: "mcq" | "code" | "open"
- question: the question text
- options: array of 4 strings (only for mcq, null otherwise)
- answer: the correct answer
- explanation: why this is correct
- difficulty: 1-5
- concepts: array of concept names tested

Return ONLY a JSON array."""

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
        self, question: str, answer: str, correct_answer: str, exercise_type: str,
    ) -> dict:
        if exercise_type == "mcq":
            is_correct = answer.strip().lower() == correct_answer.strip().lower()
            return {
                "score": 100.0 if is_correct else 0.0,
                "feedback": "正确！" if is_correct else f"正确答案是：{correct_answer}",
            }

        prompt = f"""Evaluate this student's answer:
Question: {question}
Correct answer: {correct_answer}
Student's answer: {answer}

Return JSON: {{"score": <0-100>, "feedback": "<constructive feedback in Chinese>"}}"""

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
