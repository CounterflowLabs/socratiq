"""LessonGenerator — converts subtitle chunks into structured lesson content."""

import json
import logging

from app.models.lesson import LessonContent, LessonSection
from app.models.lesson_blocks import ConceptLink, LessonBlock
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

    def _blocks_from_legacy_sections(self, content: LessonContent) -> list[LessonBlock]:
        blocks: list[LessonBlock] = [
            LessonBlock(
                type="intro_card",
                title=content.title,
                body=content.summary,
            )
        ]

        for section in content.sections:
            blocks.append(
                LessonBlock(
                    type="prose",
                    title=section.heading,
                    body=section.content,
                    metadata={"timestamp": section.timestamp},
                )
            )

            if section.key_concepts:
                blocks.append(
                    LessonBlock(
                        type="concept_relation",
                        title=section.heading,
                        concepts=[ConceptLink(label=concept) for concept in section.key_concepts],
                        metadata={"section_heading": section.heading},
                    )
                )

            for snippet in section.code_snippets:
                blocks.append(
                    LessonBlock(
                        type="code_example",
                        title=section.heading,
                        body=snippet.context or section.content,
                        code=snippet.code,
                        language=snippet.language,
                        metadata={"section_heading": section.heading},
                    )
                )

            for diagram in section.diagrams:
                blocks.append(
                    LessonBlock(
                        type="diagram",
                        title=diagram.title,
                        body=section.content,
                        diagram_type=diagram.type,
                        diagram_content=diagram.content,
                        metadata={"section_heading": section.heading},
                    )
                )

        blocks.append(
            LessonBlock(
                type="recap",
                title="Recap",
                body=content.summary,
            )
        )
        return blocks

    async def generate(
        self,
        subtitle_chunks: list[str],
        video_title: str,
        goal: str | None = None,
    ) -> LessonContent:
        """Convert subtitle chunks into structured lesson content."""
        subtitles = "\n\n".join(subtitle_chunks)
        goal_prompt = f"\n\nLearning goal: {goal}" if goal else ""

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(
                    role="user",
                    content=LESSON_PROMPT.format(
                        title=video_title,
                        subtitles=subtitles[:8000],
                    )
                    + goal_prompt,
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
            content = LessonContent(**data)
            if not content.blocks:
                content.blocks = self._blocks_from_legacy_sections(content)
            return content

        except Exception as e:
            logger.error(f"Lesson generation failed: {e}")
            # Fallback: wrap raw subtitle text as a single section
            content = LessonContent(
                title=video_title,
                summary="",
                sections=[LessonSection(
                    heading=video_title,
                    content=subtitles[:3000],
                    timestamp=0.0,
                )],
            )
            content.blocks = self._blocks_from_legacy_sections(content)
            return content
