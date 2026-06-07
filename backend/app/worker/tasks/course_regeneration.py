"""Course regeneration Celery task.

Tier 2: regeneration is just course generation again with a directive
threaded through. The previous _refresh_source_metadata function and its
side-effect of overwriting shared ``source.metadata_`` is gone — lessons
and labs now live on the per-course Section / Lab rows.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db.models.course import Course, CourseSource
from app.db.models.source import Source
from app.services.course_generator import CourseGenerator
from app.services.profile import load_profile
from app.services.source_tasks import mark_source_task
from app.worker._compat import task_shim
from app.worker.tasks.course_generation import _maybe_run_agentic_outline

logger = logging.getLogger(__name__)


async def regenerate_course(
    ctx: dict,
    parent_course_id: str,
    user_directive: str,
    user_id: str,
) -> dict:
    """ARQ entry point. Returns ``{course_id, parent_course_id, status}``."""
    return await _regenerate_course_async(
        task_shim(ctx), parent_course_id, user_directive, user_id, ctx["resources"]
    )


async def _regenerate_course_async(
    task,
    parent_course_id: str,
    user_directive: str,
    user_id: str,
    resources,
) -> dict:
    from app.services.source_tasks import TaskCancelledError, is_cancel_requested

    parent_uuid = UUID(parent_course_id)
    user_uuid = UUID(user_id)
    directive = user_directive.strip()

    # Cooperative cancel: poll the first linked source's
    # ``course_regeneration`` row for the flag at every chunk break point.
    # The cancel endpoint sets cancel_requested on the matched row. Anchor
    # is resolved once source_ids is known; we hand the closure a mutable
    # 1-slot holder so it picks up the assignment later in this function.
    anchor_holder: list[UUID] = []

    async def _check_cancel():
        if not anchor_holder:
            return
        async with resources.session_factory() as poll_db:
            if await is_cancel_requested(
                poll_db,
                source_id=anchor_holder[0],
                task_type="course_regeneration",
            ):
                raise TaskCancelledError(
                    f"course_regeneration cancelled for {parent_course_id}"
                )

    try:
        async with resources.session_factory() as db:
            parent_course = await db.get(Course, parent_uuid)
            if parent_course is None:
                raise ValueError(f"Parent course {parent_course_id} not found")

            cs_rows = (
                await db.execute(
                    select(CourseSource).where(CourseSource.course_id == parent_uuid)
                )
            ).scalars().all()
            source_ids = [cs.source_id for cs in cs_rows]
            if not source_ids:
                raise ValueError(
                    f"Course {parent_course_id} has no linked sources to regenerate"
                )
            anchor_holder.append(source_ids[0])

            for sid in source_ids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_regeneration",
                    status="running",
                    stage="generating",
                    celery_task_id=_self_task_id(task),
                )

            user_profile = await load_profile(db, user_uuid)
            target_language = user_profile.preferred_language

            task.update_state(state="PROGRESS", meta={"stage": "generating"})

            # Agentic outline (Phase 3): re-plan the section structure with the
            # critic-gated video→course graph before regenerating, so
            # regenerated courses get the consolidated outline too (not just the
            # initial generate path). Gated on the flag; per-source failures
            # fall back to the existing buckets.
            if get_settings().agentic_video_pipeline:
                for sid in source_ids:
                    src = await db.get(Source, sid)
                    if src is None:
                        continue
                    try:
                        if await _maybe_run_agentic_outline(
                            db, src, sid, resources, None, target_language
                        ):
                            await db.commit()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Agentic outline (regenerate) failed for %s; using "
                            "existing buckets: %s",
                            sid,
                            exc,
                        )
                        await db.rollback()

            generator = CourseGenerator(resources.model_router)
            new_course = await generator.generate(
                db=db,
                source_ids=source_ids,
                target_language=target_language,
                title=parent_course.title,
                user_id=user_uuid,
                skip_ready_check=True,
                user_directive=directive,
                cancel_check=_check_cancel,
            )

            new_course.parent_id = parent_uuid
            new_course.regeneration_directive = directive or None
            new_course.regeneration_metadata = {
                "model_used": await _resolve_chat_model_name(db),
                "generated_at": datetime.utcnow().isoformat(),
                "source_ids": [str(s) for s in source_ids],
            }
            await db.flush()

            for sid in source_ids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_regeneration",
                    status="success",
                    stage="ready",
                    metadata_={"new_course_id": str(new_course.id)},
                )

            await db.commit()

            logger.info(
                "Regenerated course %s -> %s (directive=%r)",
                parent_course_id,
                new_course.id,
                directive,
            )

            return {
                "course_id": str(new_course.id),
                "parent_course_id": parent_course_id,
                "status": "success",
            }
    except TaskCancelledError as exc:
        logger.info(
            "Course regeneration cancelled for %s: %s", parent_course_id, exc
        )
        try:
            async with resources.session_factory() as db:
                cs_rows2 = (
                    await db.execute(
                        select(CourseSource).where(CourseSource.course_id == parent_uuid)
                    )
                ).scalars().all()
                for cs in cs_rows2:
                    await mark_source_task(
                        db,
                        source_id=cs.source_id,
                        task_type="course_regeneration",
                        status="cancelled",
                        stage="cancelled",
                    )
                await db.commit()
        except Exception:
            logger.warning("Failed to record regeneration cancel marker", exc_info=True)
        return {
            "parent_course_id": parent_course_id,
            "status": "cancelled",
        }
    except Exception as exc:
        logger.error(
            "Course regeneration failed for %s: %s",
            parent_course_id,
            exc,
            exc_info=True,
        )
        try:
            async with resources.session_factory() as db:
                cs_rows = (
                    await db.execute(
                        select(CourseSource).where(CourseSource.course_id == parent_uuid)
                    )
                ).scalars().all()
                for cs in cs_rows:
                    await mark_source_task(
                        db,
                        source_id=cs.source_id,
                        task_type="course_regeneration",
                        status="failure",
                        stage="error",
                        error_summary=str(exc)[:500],
                    )
                await db.commit()
        except Exception:
            logger.warning("Failed to record regeneration failure marker", exc_info=True)
        raise


def _self_task_id(task) -> str | None:
    request = getattr(task, "request", None)
    return getattr(request, "id", None) if request is not None else None


async def _resolve_chat_model_name(db) -> str:
    """Look up the model assigned to the content_analysis route, for audit."""
    from app.db.models.model_config import ModelRouteConfig
    from sqlalchemy import select as _select

    row = (
        await db.execute(
            _select(ModelRouteConfig.model_name).where(
                ModelRouteConfig.task_type == "content_analysis"
            )
        )
    ).first()
    return row[0] if row else "unknown"
