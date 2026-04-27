"""Course regeneration Celery task.

Re-runs the content pipeline (analyze → plan → lessons → labs → assemble) for
the sources backing an existing course, optionally guided by a free-text user
directive. Produces a *new* Course row whose ``parent_id`` points at the
caller-selected version, leaving the original course (and any other versions)
untouched.

Reuses helpers / services from ``content_ingestion`` rather than re-extracting
chunks: source-level extraction is unchanged across regenerations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.course import Course, CourseSource
from app.db.models.source import Source
from app.models.lesson import CodeSnippet
from app.services.content_analyzer import ContentAnalyzer
from app.services.course_generator import CourseGenerator
from app.services.lab_generator import LabGenerator
from app.services.lesson_generator import LessonGenerator
from app.services.llm.router import TaskType
from app.services.profile import load_profile
from app.services.source_tasks import mark_source_task
from app.services.teaching_asset_planner import TeachingAssetPlanner
from app.tools.extractors.base import RawContentChunk
from app.worker.celery_app import celery_app
from app.worker.tasks.content_ingestion import _create_worker_resources

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="course_regeneration.regenerate_course",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=900,
    time_limit=960,
)
def regenerate_course(
    self,
    parent_course_id: str,
    user_directive: str,
    user_id: str,
) -> dict:
    """Celery entry point. Returns ``{course_id, parent_course_id, status}``."""
    return asyncio.run(
        _regenerate_course_async(self, parent_course_id, user_directive, user_id)
    )


async def _regenerate_course_async(
    task,
    parent_course_id: str,
    user_directive: str,
    user_id: str,
) -> dict:
    parent_uuid = UUID(parent_course_id)
    user_uuid = UUID(user_id)
    directive = user_directive.strip()

    resources = _create_worker_resources()

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

            user_profile = await load_profile(db, user_uuid)
            target_language = user_profile.preferred_language

            for sid in source_ids:
                await _refresh_source_metadata(
                    task=task,
                    db=db,
                    source_id=sid,
                    target_language=target_language,
                    user_directive=directive,
                    resources=resources,
                )
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_regeneration",
                    status="running",
                    stage="source_done",
                    celery_task_id=self_task_id(task),
                )

            task.update_state(state="PROGRESS", meta={"stage": "assembling"})

            generator = CourseGenerator(resources.model_router)
            new_course = await generator.generate(
                db=db,
                source_ids=source_ids,
                target_language=target_language,
                title=parent_course.title,
                user_id=user_uuid,
                skip_ready_check=True,
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
    finally:
        await resources.engine.dispose()


async def _refresh_source_metadata(
    *,
    task,
    db,
    source_id: UUID,
    target_language: str,
    user_directive: str,
    resources,
) -> None:
    """Re-run analyze -> plan -> lessons -> labs and overwrite source.metadata_."""
    source = await db.get(Source, source_id)
    if source is None:
        raise ValueError(f"Source {source_id} not found during regeneration")

    chunk_rows = (
        await db.execute(
            select(ContentChunkModel)
            .where(ContentChunkModel.source_id == source_id)
            .order_by(ContentChunkModel.created_at)
        )
    ).scalars().all()
    if not chunk_rows:
        raise ValueError(
            f"Source {source_id} has no extracted chunks; re-ingestion required"
        )

    raw_chunks = [
        RawContentChunk(
            source_type=source.type,
            raw_text=row.text,
            metadata=dict(row.metadata_ or {}),
        )
        for row in chunk_rows
    ]

    task.update_state(
        state="PROGRESS",
        meta={"stage": "analyzing", "source_id": str(source_id)},
    )
    analyzer = ContentAnalyzer(resources.model_router)
    analysis = await analyzer.analyze(
        title=source.title or "Untitled",
        chunks=raw_chunks,
        source_type=source.type,
        user_directive=user_directive,
    )

    planner = TeachingAssetPlanner()
    asset_plan = planner.plan(
        source_title=source.title or "Untitled",
        source_type=source.type,
        overall_summary=analysis.overall_summary,
        chunk_topics=[c.topic for c in analysis.chunks],
        has_code=any(c.has_code for c in analysis.chunks),
    )

    task.update_state(
        state="PROGRESS",
        meta={"stage": "generating_lessons", "source_id": str(source_id)},
    )

    lesson_provider = await resources.model_router.get_provider(
        TaskType.CONTENT_ANALYSIS
    )
    lesson_gen = LessonGenerator(lesson_provider)

    page_groups: dict[int, list] = {}
    for chunk in analysis.chunks:
        page_idx = chunk.metadata.get("page_index", 0)
        page_groups.setdefault(page_idx, []).append(chunk)

    sorted_pages = sorted(page_groups.keys())
    total_lessons = len(sorted_pages)
    lesson_by_page: dict[int, object] = {}
    for i, page_idx in enumerate(sorted_pages):
        task.update_state(
            state="PROGRESS",
            meta={
                "stage": "generating_lessons",
                "current": i + 1,
                "total": total_lessons,
                "source_id": str(source_id),
            },
        )
        page_chunks = page_groups[page_idx]
        chunk_texts = [c.raw_text for c in page_chunks]
        page_title = (
            page_chunks[0].metadata.get("page_title")
            or source.title
            or "Untitled"
        )
        lesson_content = await lesson_gen.generate(
            chunk_texts,
            page_title,
            target_language=target_language,
            user_directive=user_directive,
        )
        lesson_by_page[page_idx] = lesson_content

    graph_by_page: dict[int, dict] = {}
    for page_idx, lesson_content in lesson_by_page.items():
        key_concepts: list[str] = []
        for block in lesson_content.blocks:
            if block.type == "concept_relation":
                key_concepts.extend(c.label for c in block.concepts)
        deduped = list(dict.fromkeys(key_concepts))
        graph_by_page[page_idx] = {
            "current": deduped[:2],
            "prerequisites": analysis.suggested_prerequisites[:3],
            "unlocks": deduped[2:5],
            "section_anchor": page_idx,
        }

    labs_by_page: dict[int, dict | None] = {}
    if asset_plan.lab_mode == "inline":
        lab_gen = LabGenerator(lesson_provider)
        lab_pages = list(lesson_by_page.items())
        total_labs = len(lab_pages)
        for i, (page_idx, lesson_content) in enumerate(lab_pages):
            task.update_state(
                state="PROGRESS",
                meta={
                    "stage": "generating_labs",
                    "current": i + 1,
                    "total": total_labs,
                    "source_id": str(source_id),
                },
            )
            all_snippets = [
                CodeSnippet(
                    language=block.language or "python",
                    code=block.code,
                    context=block.body or "",
                )
                for block in lesson_content.blocks
                if block.type == "code_example" and block.code
            ]
            if not all_snippets:
                labs_by_page[page_idx] = None
                continue

            lang_counts: dict[str, int] = {}
            for snippet in all_snippets:
                lang_counts[snippet.language] = lang_counts.get(snippet.language, 0) + 1
            language = max(lang_counts, key=lang_counts.__getitem__)

            lab_result = await lab_gen.generate(
                code_snippets=all_snippets,
                lesson_context=lesson_content.summary,
                language=language,
                target_language=target_language,
                user_directive=user_directive,
            )
            labs_by_page[page_idx] = lab_result

    source.metadata_ = {
        **(source.metadata_ or {}),
        "overall_summary": analysis.overall_summary,
        "overall_difficulty": analysis.overall_difficulty,
        "concept_count": len(analysis.concepts),
        "chunk_count": len(analysis.chunks),
        "estimated_study_minutes": analysis.estimated_study_minutes,
        "suggested_prerequisites": analysis.suggested_prerequisites,
        "asset_plan": asset_plan.model_dump(),
        "lesson_by_page": {
            str(page_idx): lesson.model_dump()
            for page_idx, lesson in lesson_by_page.items()
        },
        "graph_by_page": {
            str(page_idx): graph for page_idx, graph in graph_by_page.items()
        },
        "labs_by_page": {
            str(page_idx): lab_data
            for page_idx, lab_data in labs_by_page.items()
            if lab_data is not None
        },
    }
    await db.flush()


def self_task_id(task) -> str | None:
    """Return the celery task id when available."""
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
