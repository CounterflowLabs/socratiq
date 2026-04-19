"""LessonGenerator — converts subtitle chunks into structured lesson content."""

import json
import logging

from app.models.lesson import LessonContent, LessonSection
from app.services.llm.base import LLMProvider, UnifiedMessage

logger = logging.getLogger(__name__)

LESSON_PROMPT = """You are a course content editor. Convert the following video subtitle text into a structured lesson.

Video title: {title}

Subtitle text:
{subtitles}

Instructions:
1. Identify topic shifts and create section headings
2. Rewrite spoken/informal language into clear written prose — do NOT invent facts
3. Extract any code that was spoken about (e.g. "let's write def hello" → code block)
4. When content describes a process, flow, or architecture, generate a Mermaid diagram
5. When content is a step-by-step procedure, output a StepByStep structure
6. Preserve approximate timestamps from the original text
7. List key concepts per section

Return ONLY valid JSON matching this schema:
{{
  "title": "...",
  "summary": "1-2 sentence overview",
  "sections": [
    {{
      "heading": "Section title",
      "content": "Written prose...",
      "timestamp": 30.0,
      "code_snippets": [{{"language": "python", "code": "x = 5", "context": "explanation"}}],
      "key_concepts": ["concept1"],
      "diagrams": [{{"type": "mermaid", "title": "Flow", "content": "graph LR\\n  A-->B"}}],
      "interactive_steps": null or {{"title": "...", "steps": [{{"label": "Step 1", "detail": "...", "code": null}}]}}
    }}
  ]
}}"""


class LessonGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def generate(self, subtitle_chunks: list[str], video_title: str) -> LessonContent:
        """Convert subtitle chunks into structured lesson content."""
        subtitles = "\n\n".join(subtitle_chunks)

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(
                    role="user",
                    content=LESSON_PROMPT.format(title=video_title, subtitles=subtitles[:8000]),
                )],
                max_tokens=4000,
                temperature=0.3,
            )

            text = response.content[0].text if response.content else "{}"
            # Extract JSON from markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)
            return LessonContent(**data)

        except Exception as e:
            logger.error(f"Lesson generation failed: {e}")
            # Fallback: wrap raw subtitle text as a single section
            return LessonContent(
                title=video_title,
                summary="",
                sections=[LessonSection(
                    heading=video_title,
                    content=subtitles[:3000],
                    timestamp=0.0,
                )],
            )
