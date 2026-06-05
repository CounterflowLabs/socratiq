"""Celery task for regenerating a single section's lesson.

When the original course-generation run failed for one chunk, the section
row carries ``lesson_generation_error`` and no ``content.lesson``. The user
hits "重试" in the UI; this task re-runs ``LessonGenerator`` against the
chunks linked to that section and writes the result back in place.

Mirrors the per-section locking pattern in :mod:`exercise_generation`: a
single ``active_lesson_task_id`` slot prevents concurrent retries on the
same section.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def regenerate_section_lesson(
    ctx: dict,
    section_id: str,
    user_id: str,
) -> dict:
    """ARQ entry point — wraps the async implementation."""
    return await _regenerate_section_lesson_async(
        section_id, user_id, ctx["resources"]
    )


async def _regenerate_section_lesson_async(
    section_id: str,
    user_id: str,
    resources,
) -> dict:
    from sqlalchemy import select

    from app.db.models.content_chunk import ContentChunk
    from app.db.models.course import Section
    from app.services.lesson_generator import (
        LessonGenerationError,
        LessonGenerator,
    )
    from app.services.llm.router import TaskType
    from app.services.profile import load_profile

    sid = UUID(section_id)
    uid = UUID(user_id)

    async with resources.session_factory() as db:
        section = await db.get(Section, sid)
        if section is None:
            logger.warning("Lesson regeneration: section %s missing", section_id)
            return {"section_id": section_id, "status": "missing"}

        try:
            chunks = (await db.execute(
                select(ContentChunk)
                .where(ContentChunk.section_id == sid)
                .order_by(ContentChunk.created_at)
            )).scalars().all()
            if not chunks:
                section.lesson_generation_error = (
                    "本节没有可用的原始内容，无法重新生成。"
                )
                section.active_lesson_task_id = None
                await db.commit()
                return {"section_id": section_id, "status": "no_chunks"}

            profile = await load_profile(db, uid)
            provider = await resources.model_router.get_provider(
                TaskType.CONTENT_ANALYSIS
            )
            generator = LessonGenerator(provider)

            first_meta = chunks[0].metadata_ or {}
            video_title = (
                first_meta.get("page_title")
                or first_meta.get("topic")
                or section.title
                or "Untitled"
            )

            lesson = await generator.generate(
                subtitle_chunks=[c.text for c in chunks],
                video_title=video_title,
                target_language=profile.preferred_language,
            )

            # Stitch the freshly generated lesson back into section.content
            # without touching the other keys (summary, lab_mode, graph_card,
            # key_terms, has_code).
            content = dict(section.content or {})
            content["lesson"] = lesson.model_dump()
            if lesson.summary:
                content["summary"] = lesson.summary
            section.content = content
            section.title = lesson.title or section.title
            section.lesson_generation_error = None
            section.active_lesson_task_id = None
            await db.commit()

            logger.info("Regenerated lesson for section %s", section_id)
            return {"section_id": section_id, "status": "ready"}

        except LessonGenerationError as exc:
            logger.warning(
                "Lesson regeneration gave up for section %s: %s", section_id, exc
            )
            await _record_section_failure(resources, sid, str(exc))
            return {"section_id": section_id, "status": "error", "error": str(exc)}
        except Exception as exc:
            logger.error(
                "Lesson regeneration crashed for section %s: %s",
                section_id,
                exc,
                exc_info=True,
            )
            await _record_section_failure(resources, sid, str(exc))
            raise


async def _record_section_failure(resources, section_id: UUID, error: str) -> None:
    """Clear the lock and store the error in a fresh session.

    Done in its own session so a partial transaction from the failing run
    cannot block the lock from being released.
    """
    from app.db.models.course import Section

    try:
        async with resources.session_factory() as db:
            section = await db.get(Section, section_id)
            if section is not None:
                section.active_lesson_task_id = None
                section.lesson_generation_error = (error or "Lesson generation failed")[
                    :500
                ]
                await db.commit()
    except Exception:
        logger.exception("Failed to record lesson failure for %s", section_id)
