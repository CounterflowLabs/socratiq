"""Celery task for true multi-source course generation.

The single-source ``course_generation.generate_course`` runs once per source
and produces N independent courses. PRD §5.4 step 1 lets the user pick a
*combination* of sources and synthesize **one** course from all of them.
This task wraps :meth:`CourseGenerator.generate` directly with the picked
source list and the config-derived directive.

The anchor source — the first one in ``source_ids`` — owns the
``source_tasks`` row so the existing per-source progress endpoints keep
working unchanged. The other sources are recorded in
``metadata_.source_ids`` so the unified Tasks queue can show them all.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.services.source_tasks import mark_source_task
from app.worker._compat import task_shim

logger = logging.getLogger(__name__)


_AUDIENCE_HINT = {
    "intro": "入门读者：用类比与最少的术语；先建直觉，再讲机制。",
    "mid": "中级读者：默认读者会基础术语，但仍需要清楚的推理链路。",
    "adv": "进阶读者：可以引入精确表述与高级概念；省略基础铺垫。",
}
_LANG_HINT = {
    "source": "课程语言与原始资料保持一致。",
    "zh": "用中文输出全部课文与标题。",
    "en": "Output the entire course in English.",
}


def build_directive_from_config(config: dict[str, Any]) -> str:
    """Fold the step-2 config form into a natural-language directive that
    :class:`LessonGenerator` already knows how to honor via its
    ``{{ user_directive }}`` placeholder."""
    parts: list[str] = []
    brief = (config.get("brief") or "").strip()
    if brief:
        parts.append(brief)
    depth = config.get("depth")
    if depth:
        parts.append(f"目标课文总数约 {depth} 节。")
    audience_hint = _AUDIENCE_HINT.get(str(config.get("audience") or "mid"))
    if audience_hint:
        parts.append(audience_hint)
    lang_hint = _LANG_HINT.get(str(config.get("language") or "source"))
    if lang_hint:
        parts.append(lang_hint)
    includes = config.get("includes") or {}
    excluded: list[str] = []
    if includes.get("exercises") is False:
        excluded.append("练习题")
    if includes.get("lab") is False:
        excluded.append("Lab 代码实验")
    if includes.get("review") is False:
        excluded.append("复习卡")
    if excluded:
        parts.append("不要包含：" + "、".join(excluded) + "。")
    weights = config.get("source_weights") or {}
    emphasized = [sid[:8] for sid, w in weights.items() if w and w > 1]
    deemphasized = [sid[:8] for sid, w in weights.items() if w is not None and w < 1]
    if emphasized:
        parts.append("更侧重的资料：" + "、".join(emphasized) + "。")
    if deemphasized:
        parts.append("淡化的资料：" + "、".join(deemphasized) + "。")
    return "\n".join(parts)


async def generate_multi(
    ctx: dict,
    payload: dict[str, Any],
    user_id: str | None = None,
) -> dict:
    """ARQ entry: synthesize one course from multiple sources."""
    source_ids = payload["source_ids"]
    title = payload.get("title")
    config = payload.get("config", {})
    return await _generate_multi_async(
        task_shim(ctx), source_ids, title, config, user_id, ctx["resources"]
    )


async def _generate_multi_async(
    task,
    source_ids: list[str],
    title: str | None,
    config: dict[str, Any],
    user_id: str | None,
    resources,
) -> dict:
    from sqlalchemy import select

    from app.db.models.source import Source
    from app.services.course_generator import CourseGenerator
    from app.services.profile import load_profile
    from app.services.source_tasks import (
        TaskCancelledError,
        is_cancel_requested,
        mark_source_task,
    )

    sids = [UUID(s) for s in source_ids]
    anchor = sids[0]
    uid = UUID(user_id) if user_id else None

    # Cooperative cancel: the anchor source_tasks row carries the
    # cancel_requested flag for the whole cohort; we poll it from a
    # short-lived session at each chunk-level break point.
    async def _check_cancel():
        async with resources.session_factory() as poll_db:
            if await is_cancel_requested(
                poll_db, source_id=anchor, task_type="course_generation"
            ):
                raise TaskCancelledError(
                    f"course_generation cancelled for sources {source_ids}"
                )

    async def _report_section_progress(source_id: UUID, progress: dict[str, Any]) -> None:
        async with resources.session_factory() as progress_db:
            await mark_source_task(
                progress_db,
                source_id=source_id,
                task_type="course_generation",
                status="running",
                stage="assembling_course",
                metadata_={"section_progress": progress},
            )
            await progress_db.commit()

    try:
        async with resources.session_factory() as db:
            sources = (
                await db.execute(select(Source).where(Source.id.in_(sids)))
            ).scalars().all()
            by_id = {s.id: s for s in sources}
            missing = [str(s) for s in sids if s not in by_id]
            if missing:
                raise ValueError(f"Sources not found: {missing}")
            for s in sources:
                if s.status != "ready":
                    raise ValueError(
                        f"Source {s.id} is {s.status!r}; only ready sources can generate a course"
                    )

            for sid in sids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_generation",
                    status="running",
                    stage="planning",
                )
            await db.commit()
            task.update_state(state="PROGRESS", meta={"stage": "planning"})

            target_language = "zh-CN"
            cfg_lang = str(config.get("language") or "source")
            if cfg_lang == "zh":
                target_language = "zh-CN"
            elif cfg_lang == "en":
                target_language = "en"
            elif uid is not None:
                target_language = (await load_profile(db, uid)).preferred_language

            directive = build_directive_from_config(config)
            if not title:
                first = by_id[anchor]
                title = first.title or "Untitled course"
                if len(sids) > 1:
                    title = f"{title} + {len(sids) - 1} more"

            generator = CourseGenerator(resources.model_router)
            course = await generator.generate(
                db=db,
                source_ids=sids,
                title=title,
                user_id=uid,
                target_language=target_language,
                user_directive=directive,
                skip_ready_check=True,
                cancel_check=_check_cancel,
                section_progress_callback=_report_section_progress,
            )

            for sid in sids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_generation",
                    status="success",
                    stage="ready",
                    metadata_={"course_id": str(course.id), "source_ids": [str(s) for s in sids]},
                )
            await db.commit()

            logger.info(
                "Generated multi-source course '%s' from %d sources -> %s",
                title,
                len(sids),
                course.id,
            )
            return {
                "course_id": str(course.id),
                "source_ids": source_ids,
                "title": title,
                "status": "ready",
            }
    except TaskCancelledError as exc:
        logger.info("Multi-source generation cancelled: %s", exc)
        async with resources.session_factory() as db:
            for sid in sids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_generation",
                    status="cancelled",
                    stage="cancelled",
                )
            await db.commit()
        return {"source_ids": source_ids, "status": "cancelled"}
    except Exception as exc:
        async with resources.session_factory() as db:
            for sid in sids:
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_generation",
                    status="failure",
                    stage="error",
                    error_summary=str(exc)[:500],
                )
            await db.commit()
        raise
