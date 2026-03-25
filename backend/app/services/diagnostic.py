"""Cold-start diagnostic service — LLM-generated assessment questions."""

import json
import logging

from app.models.diagnostic import DiagnosticQuestion, DiagnosticResult
from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)


class DiagnosticService:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate(self, concepts: list[dict], count: int = 5) -> list[DiagnosticQuestion]:
        concept_text = "\n".join(
            f"- {c['name']}: {c.get('description', '')}" for c in concepts
        )
        prompt = f"""Generate {count} multiple-choice diagnostic questions to assess a student's knowledge of these concepts:

{concept_text}

Requirements:
- Order from easiest to hardest (difficulty 1-5)
- Each question has exactly 4 options
- Test understanding, not memorization

Return ONLY a JSON array:
[{{"id": "q1", "concept_id": "<uuid>", "question": "...", "options": ["A","B","C","D"], "correct_index": 0, "difficulty": 1}}]"""

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(role="user", content=prompt)],
                max_tokens=2000,
                temperature=0.7,
            )
            text = response.content[0].text if response.content else "[]"
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            raw = json.loads(text)
        except Exception as e:
            logger.error(f"Diagnostic generation failed: {e}")
            return []

        questions = []
        for item in raw[:count]:
            try:
                questions.append(DiagnosticQuestion(**item))
            except Exception as e:
                logger.warning(f"Skipping malformed question: {e}")
        return questions

    def evaluate(self, questions: list[dict], answers: list[dict]) -> DiagnosticResult:
        answer_map = {a["question_id"]: a["selected_answer"] for a in answers}
        correct = 0
        mastered = []
        gaps = []
        for q in questions:
            if answer_map.get(q["id"]) == q["correct_index"]:
                correct += 1
                mastered.append(q["concept_name"])
            else:
                gaps.append(q["concept_name"])
        total = len(questions) or 1
        score = (correct / total) * 100
        level = "advanced" if score >= 80 else "intermediate" if score >= 40 else "beginner"
        return DiagnosticResult(level=level, mastered_concepts=mastered, gaps=gaps, score=round(score, 1))
