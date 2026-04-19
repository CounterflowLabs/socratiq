"""LabGenerator — creates code labs from lesson code snippets."""

import json
import logging

from app.models.lesson import CodeSnippet
from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)

RUN_TEMPLATES = {
    "python": "```bash\ncd {lab_dir}\npip install -r requirements.txt  # if exists\npython -m pytest tests/ -v\n```",
    "go": "```bash\ncd {lab_dir}\ngo test ./... -v\n```",
    "javascript": "```bash\ncd {lab_dir}\nnpm install\nnpm test\n```",
    "typescript": "```bash\ncd {lab_dir}\nnpm install\nnpm test\n```",
}

LAB_PROMPT = """You are a programming course lab designer. Create a hands-on coding exercise based on these code examples from a tutorial.

Code snippets from the lesson:
{snippets}

Lesson context:
{context}

Programming language: {language}

Instructions:
1. Create a complete reference solution (solution_code) based on the code snippets
2. Create starter code (starter_code) by removing key implementations and replacing with TODO comments
3. Create test files (test_code) that verify the solution works
4. The starter code + tests should be self-consistent — a student filling in the TODOs correctly should pass all tests
5. Include clear descriptions of what each TODO requires

Return ONLY valid JSON:
{{
  "title": "Lab title",
  "description": "## Objective\\n...\\n## Background\\n...",
  "language": "{language}",
  "starter_code": {{"filename.py": "code with TODOs..."}},
  "test_code": {{"test_filename.py": "test code..."}},
  "solution_code": {{"filename.py": "complete solution..."}},
  "run_instructions": "how to run tests",
  "confidence": 0.0-1.0
}}"""


class LabGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate(
        self,
        code_snippets: list[CodeSnippet],
        lesson_context: str,
        language: str,
        goal: str | None = None,
    ) -> dict | None:
        """Generate a lab from code snippets. Returns None if no code or low confidence."""
        if not code_snippets:
            return None

        snippets_text = "\n\n".join(
            f"```{s.language}\n{s.code}\n```\nContext: {s.context}" for s in code_snippets
        )
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(
                    role="user",
                    content=LAB_PROMPT.format(
                        snippets=snippets_text, context=lesson_context[:3000], language=language,
                    )
                    + goal_prompt,
                )],
                max_tokens=4000,
                temperature=0.3,
            )

            text = response.content[0].text if response.content else "{}"
            stripped = text.strip()
            if stripped.startswith("```"):
                # Strip markdown code fence wrapping the JSON
                text = stripped.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)

            # Check confidence threshold
            if data.get("confidence", 0) < 0.3:
                logger.info(f"Lab confidence too low ({data.get('confidence')}), skipping")
                return None

            # Add run instructions template if not provided
            if not data.get("run_instructions"):
                template = RUN_TEMPLATES.get(language, RUN_TEMPLATES["python"])
                data["run_instructions"] = template.format(lab_dir=f"lab_{data.get('title', 'exercise').lower().replace(' ', '_')}")

            return data

        except Exception as e:
            logger.error(f"Lab generation failed: {e}")
            return None
