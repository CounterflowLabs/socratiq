"""Celery task for asynchronous exercise generation per section.

Replaces the synchronous ``POST /exercises/section/{id}/generate`` handler
that would block the request thread for ~50s on slow LLM backends. The
section row carries a single ``active_exercise_task_id`` slot, so per
section only one generation task may be in flight at a time.
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def generate_section_exercises(
    ctx: dict,
    section_id: str,
    count: int,
    types: list[str] | None,
    user_id: str,
) -> dict:
    """ARQ entry point — wraps the async implementation."""
    return await _generate_section_exercises_async(
        section_id, count, types, user_id, ctx["resources"]
    )


async def _generate_section_exercises_async(
    section_id: str,
    count: int,
    types: list[str] | None,
    user_id: str,
    resources,
) -> dict:
    from sqlalchemy import select

    from app.db.models.course import Section
    from app.db.models.exercise import Exercise
    from app.services.exercise import ExerciseService
    from app.services.llm.router import TaskType
    from app.services.profile import load_profile

    sid = UUID(section_id)
    uid = UUID(user_id)

    async with resources.session_factory() as db:
        section = await db.get(Section, sid)
        if section is None:
            logger.warning("Exercise generation: section %s missing", section_id)
            return {"section_id": section_id, "status": "missing", "created": 0}

        try:
            content = _extract_lesson_content(section.content)
            if not content.strip():
                section.exercise_generation_error = "本节没有可用于生成练习的课程内容。"
                section.active_exercise_task_id = None
                await db.commit()
                return {"section_id": section_id, "status": "no_content", "created": 0}

            profile = await load_profile(db, uid)
            provider = await resources.model_router.get_provider(TaskType.EVALUATION)
            service = ExerciseService(provider)
            raw_items = await service.generate_from_content(
                content=content,
                count=count,
                types=types,
                target_language=profile.preferred_language,
            )

            created: list[Exercise] = []
            for item in raw_items:
                if not isinstance(item, dict) or not item.get("question"):
                    continue
                exercise = Exercise(
                    section_id=sid,
                    type=str(item.get("type") or "open"),
                    question=str(item["question"]),
                    options=item.get("options"),
                    answer=item.get("answer"),
                    explanation=item.get("explanation"),
                    difficulty=int(item.get("difficulty") or 3),
                    concepts=[],
                )
                db.add(exercise)
                created.append(exercise)
            # Re-load section in this session before clearing the flag (the
            # earlier `await db.get` instance is still tracked, but we want a
            # single commit at the end).
            section.active_exercise_task_id = None
            if created:
                section.exercise_generation_error = None
            else:
                section.exercise_generation_error = (
                    "未能生成有效练习题，请稍后重试。"
                )
            await db.commit()
            logger.info(
                "Generated %d exercises for section %s", len(created), section_id
            )
            return {
                "section_id": section_id,
                "status": "ready" if created else "empty",
                "created": len(created),
            }
        except Exception as exc:
            logger.error(
                "Exercise generation failed for section %s: %s",
                section_id,
                exc,
                exc_info=True,
            )
            # Clear the lock so the user can retry; record the error.
            try:
                async with resources.session_factory() as db2:
                    fresh = await db2.get(Section, sid)
                    if fresh is not None:
                        fresh.active_exercise_task_id = None
                        fresh.exercise_generation_error = str(exc)[:500]
                        await db2.commit()
            except Exception:
                logger.exception("Failed to clear exercise lock for %s", section_id)
            raise


def _extract_lesson_content(section_content: dict | None) -> str:
    """Mirrors the helper in app.api.routes.exercises."""
    if not section_content:
        return ""
    lesson = section_content.get("lesson") or {}
    parts: list[str] = []
    if lesson.get("title"):
        parts.append(str(lesson["title"]))
    if lesson.get("summary"):
        parts.append(str(lesson["summary"]))
    for block in lesson.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        title = block.get("title")
        body = block.get("body")
        if title:
            parts.append(str(title))
        if body:
            parts.append(str(body))
    if section_content.get("summary") and not parts:
        parts.append(str(section_content["summary"]))
    return "\n\n".join(parts)
