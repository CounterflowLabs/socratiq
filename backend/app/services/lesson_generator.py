"""LessonGenerator — converts subtitle chunks into a block-based lesson."""

import json
import logging
from pathlib import Path

from app.models.lesson import LessonContent
from app.models.lesson_blocks import LessonBlock
from app.prompt_template import load_prompt
from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "lesson_generation.md")


class LessonGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate(
        self,
        subtitle_chunks: list[str],
        video_title: str,
        target_language: str,
        goal: str | None = None,
    ) -> LessonContent:
        """Convert subtitle chunks into a block-based lesson."""
        subtitles = "\n\n".join(subtitle_chunks)
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(
                    role="user",
                    content=_PROMPT.render(
                        title=video_title,
                        target_language=target_language,
                        subtitles=subtitles[:8000],
                    )
                    + goal_prompt,
                )],
                max_tokens=4000,
                temperature=0.3,
            )

            text = response.content[0].text if response.content else "{}"
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)
            return LessonContent(**data)

        except Exception as e:
            logger.error(f"Lesson generation failed: {e}")
            return LessonContent(
                title=video_title,
                summary="",
                blocks=[
                    LessonBlock(
                        type="prose",
                        title=video_title,
                        body=subtitles[:3000],
                    )
                ],
            )
