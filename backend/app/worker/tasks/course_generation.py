"""Course generation Celery task — generates lessons, labs, and assembles course."""

import logging
from uuid import UUID

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="course_generation.generate_course",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=600,
    time_limit=660,
)
def generate_course_task(self, ingest_result: dict, goal: str | None = None, user_id: str | None = None) -> dict:
    """Generate course from an ingested source.

    Args:
        ingest_result: Result dict from ingest_source or clone_source (contains source_id).
        goal: Learning goal — "overview", "master", or "apply".
        user_id: User UUID string for course ownership.
    """
    import asyncio
    source_id = ingest_result["source_id"]
    return asyncio.run(_generate_course_async(self, source_id, goal, user_id))


async def _generate_course_async(task, source_id: str, goal: str | None, user_id: str | None) -> dict:
    """Async implementation of course generation."""
    import time
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.course import Course, CourseSource, Section
    from app.db.models.lab import Lab
    from app.services.lesson_generator import LessonGenerator
    from app.services.lab_generator import LabGenerator
    from app.services.llm.router import ModelRouter, TaskType
    from app.services.llm.base import UnifiedMessage
    from app.services.cost_guard import CostGuard
    from app.config import get_settings

    settings = get_settings()
    worker_engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    worker_session_factory = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)
    model_router = ModelRouter(session_factory=worker_session_factory, encryption_key=settings.llm_encryption_key)

    sid = UUID(source_id)
    uid = UUID(user_id) if user_id else None

    try:
        async with worker_session_factory() as db:
            source = await db.get(Source, sid)
            if not source or source.status != "ready":
                raise ValueError(f"Source {source_id} not ready for course generation")

            cost_guard = CostGuard(db)

            # Load chunks grouped by page
            result = await db.execute(
                select(ContentChunkModel)
                .where(ContentChunkModel.source_id == sid)
                .order_by(ContentChunkModel.created_at)
            )
            chunks = result.scalars().all()

            page_groups: dict[int, list] = {}
            for chunk in chunks:
                page_idx = (chunk.metadata_ or {}).get("page_index", 0)
                page_groups.setdefault(page_idx, []).append(chunk)

            # === STEP 1: GENERATE LESSONS ===
            task.update_state(state="PROGRESS", meta={"stage": "generating_lessons"})

            lesson_provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
            lesson_gen = LessonGenerator(lesson_provider)

            lesson_by_page: dict[int, object] = {}
            for page_idx in sorted(page_groups.keys()):
                page_chunks = page_groups[page_idx]
                chunk_texts = [c.text for c in page_chunks]
                page_title = (page_chunks[0].metadata_ or {}).get("page_title") or source.title or "Untitled"

                t0 = time.monotonic()
                lesson_content = await lesson_gen.generate(chunk_texts, page_title, goal=goal)
                lesson_ms = int((time.monotonic() - t0) * 1000)
                await cost_guard.log_usage(
                    user_id=uid, task_type="lesson_gen",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=lesson_ms,
                )
                lesson_by_page[page_idx] = lesson_content
                logger.info(f"Generated lesson for page {page_idx}: {len(lesson_content.sections)} sections")

            # === STEP 2: GENERATE LABS ===
            task.update_state(state="PROGRESS", meta={"stage": "generating_labs"})

            lab_gen = LabGenerator(lesson_provider)
            labs_by_page: dict[int, dict | None] = {}

            for page_idx, lesson_content in lesson_by_page.items():
                all_snippets = []
                for section in lesson_content.sections:
                    all_snippets.extend(section.code_snippets)

                if not all_snippets:
                    labs_by_page[page_idx] = None
                    continue

                lang_counts: dict[str, int] = {}
                for s in all_snippets:
                    lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
                language = max(lang_counts, key=lang_counts.__getitem__)

                t0 = time.monotonic()
                lab_result = await lab_gen.generate(
                    code_snippets=all_snippets,
                    lesson_context=lesson_content.summary,
                    language=language,
                    goal=goal,
                )
                lab_ms = int((time.monotonic() - t0) * 1000)
                await cost_guard.log_usage(
                    user_id=uid, task_type="lab_gen",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=lab_ms,
                )
                labs_by_page[page_idx] = lab_result

            # === STEP 3: ASSEMBLE COURSE ===
            task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})

            course_title = source.title or "Untitled Course"
            course = Course(title=course_title, description="", created_by=uid, goal=goal)
            db.add(course)
            await db.flush()

            db.add(CourseSource(course_id=course.id, source_id=sid))

            section_order = 0
            for page_idx in sorted(page_groups.keys()):
                page_chunks = page_groups[page_idx]
                lesson_content = lesson_by_page.get(page_idx)
                if not lesson_content:
                    continue

                first_meta = page_chunks[0].metadata_ or {}
                section_title = first_meta.get("page_title") or first_meta.get("topic") or f"Section {section_order + 1}"

                lesson_data = lesson_content.model_dump()
                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=section_order,
                    source_id=sid,
                    content={
                        "summary": lesson_content.summary,
                        "key_terms": lesson_content.sections[0].key_concepts if lesson_content.sections else [],
                        "has_code": any(s.code_snippets for s in lesson_content.sections),
                        "lesson": lesson_data,
                    },
                    difficulty=first_meta.get("difficulty", 1),
                )
                db.add(section)
                await db.flush()

                # Link chunks to section
                for chunk in page_chunks:
                    chunk.section_id = section.id

                # Create lab if available
                lab_data = labs_by_page.get(page_idx)
                if lab_data:
                    lab = Lab(
                        section_id=section.id,
                        title=lab_data.get("title", "Coding Exercise"),
                        description=lab_data.get("description", ""),
                        language=lab_data.get("language", "python"),
                        starter_code=lab_data.get("starter_code", {}),
                        test_code=lab_data.get("test_code", {}),
                        solution_code=lab_data.get("solution_code", {}),
                        run_instructions=lab_data.get("run_instructions", ""),
                        confidence=float(lab_data.get("confidence", 0.5)),
                    )
                    db.add(lab)

                section_order += 1

            await db.flush()

            # Generate course description via LLM
            try:
                provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
                response = await provider.chat(
                    messages=[UnifiedMessage(
                        role="user",
                        content=f'Write a 2-3 sentence course description for "{course_title}" with {section_order} sections. Be concise. Respond with ONLY the description.',
                    )],
                    max_tokens=256,
                    temperature=0.5,
                )
                course.description = "".join(b.text or "" for b in response.content if b.type == "text").strip()
            except Exception:
                course.description = f"A course based on {source.title or 'imported content'} with {section_order} sections."

            await db.commit()

            logger.info(f"Generated course '{course_title}' (goal={goal}) with {section_order} sections")
            return {
                "source_id": source_id,
                "course_id": str(course.id),
                "title": course_title,
                "sections_created": section_order,
                "labs_created": sum(1 for v in labs_by_page.values() if v),
                "goal": goal,
                "status": "ready",
            }
    finally:
        await worker_engine.dispose()
