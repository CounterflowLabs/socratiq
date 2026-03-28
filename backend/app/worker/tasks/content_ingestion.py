"""Content ingestion Celery tasks."""

import logging
from uuid import UUID

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="content_ingestion.ingest_source",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=600,
    time_limit=660,
)
def ingest_source(self, source_id: str) -> dict:
    """Main content ingestion pipeline task.

    Orchestrates: extract → analyze → store → embed.
    """
    import asyncio
    return asyncio.run(_ingest_source_async(self, source_id))


async def _ingest_source_async(task, source_id: str) -> dict:
    """Async implementation of the ingestion pipeline."""
    import time
    import math
    from sqlalchemy import select, update as sa_update
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.concept import Concept, ConceptSource
    from app.services.content_analyzer import ContentAnalyzer
    from app.services.embedding import EmbeddingService
    from app.services.llm.router import ModelRouter
    from app.services.time_estimator import TimeEstimator
    from app.services.cost_guard import CostGuard
    from app.tools.extractors import get_extractor
    from app.config import get_settings

    settings = get_settings()

    # Create a fresh engine + session factory for this event loop (Celery worker),
    # avoiding "Future attached to a different loop" when reusing FastAPI's engine.
    worker_engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    worker_session_factory = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)
    model_router = ModelRouter(session_factory=worker_session_factory, encryption_key=settings.llm_encryption_key)
    sid = UUID(source_id)

    try:
        async with worker_session_factory() as db:
            source = await db.get(Source, sid)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            try:
                # === STEP 1: EXTRACT ===
                await _update_status(db, sid, "extracting")
                task.update_state(state="PROGRESS", meta={"stage": "extracting"})

                extractor = _create_extractor(source)

                if source.type == "pdf":
                    file_path = source.metadata_.get("file_path", "")
                    result = await extractor.extract(file_path)
                else:
                    result = await extractor.extract(source.url or "")

                source.title = source.title or result.title
                source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)
                source.metadata_ = {**source.metadata_, **result.metadata}
                await db.flush()
                logger.info(f"Extracted {len(result.chunks)} chunks from source {source_id}")

                # --- Compute time estimate after extraction ---
                total_chars = sum(len(c.raw_text) for c in result.chunks)
                estimator = TimeEstimator(db)
                await estimator.load_calibration()
                est_code_pages = max(1, len(result.chunks) // 3)
                page_set = set()
                for c in result.chunks:
                    page_set.add(c.metadata.get("page_index", 0))
                est_page_count = len(page_set)
                cost_guard = CostGuard(db)

                # === STEP 2: ANALYZE ===
                await _update_status(db, sid, "analyzing")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
                    page_count=est_page_count, code_page_count=est_code_pages,
                    current_stage="analyzing",
                )
                task.update_state(state="PROGRESS", meta={"stage": "analyzing", "estimated_remaining_seconds": remaining})

                analyzer = ContentAnalyzer(model_router)
                t0 = time.monotonic()
                analysis = await analyzer.analyze(
                    title=source.title or "Untitled",
                    chunks=result.chunks,
                    source_type=source.type,
                )
                analyze_ms = int((time.monotonic() - t0) * 1000)
                analyze_calls = max(1, math.ceil(total_chars / 6000)) if total_chars >= 8000 else 1
                per_call_ms = analyze_ms // analyze_calls
                await cost_guard.log_usage(
                    user_id=None, task_type="content_analysis",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=per_call_ms,
                )
                logger.info(
                    f"Analyzed source {source_id}: "
                    f"{len(analysis.concepts)} concepts, "
                    f"{len(analysis.chunks)} chunks"
                )

                # === STEP 3: GENERATE LESSONS ===
                await _update_status(db, sid, "generating_lessons")

                from app.services.lesson_generator import LessonGenerator
                from app.services.llm.router import TaskType
                lesson_provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
                lesson_gen = LessonGenerator(lesson_provider)

                page_groups: dict[int, list] = {}
                for chunk in analysis.chunks:
                    page_idx = chunk.metadata.get("page_index", 0)
                    page_groups.setdefault(page_idx, []).append(chunk)

                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=est_code_pages,
                    current_stage="generating_lessons",
                )
                task.update_state(state="PROGRESS", meta={"stage": "generating_lessons", "estimated_remaining_seconds": remaining})

                lesson_by_page: dict[int, object] = {}
                for page_idx in sorted(page_groups.keys()):
                    page_chunks = page_groups[page_idx]
                    chunk_texts = [c.raw_text for c in page_chunks]
                    page_title = page_chunks[0].metadata.get("page_title") or source.title or "Untitled"
                    t0 = time.monotonic()
                    lesson_content = await lesson_gen.generate(chunk_texts, page_title)
                    lesson_ms = int((time.monotonic() - t0) * 1000)
                    await cost_guard.log_usage(
                        user_id=None, task_type="lesson_gen",
                        model_name="unknown", tokens_in=0, tokens_out=0,
                        duration_ms=lesson_ms,
                    )
                    lesson_by_page[page_idx] = lesson_content
                    logger.info(
                        f"Generated lesson for page {page_idx}: "
                        f"{len(lesson_content.sections)} sections"
                    )

                # === STEP 4: GENERATE LABS ===
                await _update_status(db, sid, "generating_labs")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=est_code_pages,
                    current_stage="generating_labs",
                )
                task.update_state(state="PROGRESS", meta={"stage": "generating_labs", "estimated_remaining_seconds": remaining})

                from app.services.lab_generator import LabGenerator
                from app.db.models.lab import Lab
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
                    )
                    lab_ms = int((time.monotonic() - t0) * 1000)
                    await cost_guard.log_usage(
                        user_id=None, task_type="lab_gen",
                        model_name="unknown", tokens_in=0, tokens_out=0,
                        duration_ms=lab_ms,
                    )
                    labs_by_page[page_idx] = lab_result
                    if lab_result:
                        logger.info(f"Generated lab for page {page_idx}: {lab_result.get('title')}")
                    else:
                        logger.info(f"No lab generated for page {page_idx} (low confidence or error)")

                # === STEP 5: STORE ===
                await _update_status(db, sid, "storing")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=0,
                    current_stage="storing",
                )
                task.update_state(state="PROGRESS", meta={"stage": "storing", "estimated_remaining_seconds": remaining})

                chunk_ids = []
                chunk_texts = []
                for analyzed_chunk in analysis.chunks:
                    db_chunk = ContentChunkModel(
                        source_id=sid,
                        text=analyzed_chunk.raw_text,
                        metadata_={
                            "topic": analyzed_chunk.topic,
                            "summary": analyzed_chunk.summary,
                            "concepts": analyzed_chunk.concepts,
                            "difficulty": analyzed_chunk.difficulty,
                            "key_terms": analyzed_chunk.key_terms,
                            "has_code": analyzed_chunk.has_code,
                            "has_formula": analyzed_chunk.has_formula,
                            **analyzed_chunk.metadata,
                        },
                    )
                    db.add(db_chunk)
                    await db.flush()
                    chunk_ids.append(db_chunk.id)
                    chunk_texts.append(analyzed_chunk.raw_text)

                concept_ids = []
                concept_texts = []
                for ext_concept in analysis.concepts:
                    concept = await _get_or_create_concept(db, ext_concept)
                    concept_ids.append(concept.id)
                    concept_texts.append(f"{concept.name}: {concept.description or ''}")

                    existing = await db.execute(
                        select(ConceptSource).where(
                            ConceptSource.concept_id == concept.id,
                            ConceptSource.source_id == sid,
                        )
                    )
                    if not existing.scalar_one_or_none():
                        db.add(
                            ConceptSource(
                                concept_id=concept.id,
                                source_id=sid,
                                context=ext_concept.description,
                            )
                        )

                source.metadata_ = {
                    **source.metadata_,
                    "overall_summary": analysis.overall_summary,
                    "overall_difficulty": analysis.overall_difficulty,
                    "concept_count": len(analysis.concepts),
                    "chunk_count": len(analysis.chunks),
                    "estimated_study_minutes": analysis.estimated_study_minutes,
                    "suggested_prerequisites": analysis.suggested_prerequisites,
                    "lesson_by_page": {
                        str(page_idx): lesson.model_dump()
                        for page_idx, lesson in lesson_by_page.items()
                    },
                    "labs_by_page": {
                        str(page_idx): lab_data
                        for page_idx, lab_data in labs_by_page.items()
                        if lab_data is not None
                    },
                }
                await db.flush()
                logger.info(f"Stored {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

                # === STEP 6: EMBED ===
                await _update_status(db, sid, "embedding")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=0,
                    current_stage="embedding",
                )
                task.update_state(state="PROGRESS", meta={"stage": "embedding", "estimated_remaining_seconds": remaining})

                embedding_service = EmbeddingService(model_router)
                await embedding_service.embed_and_store_chunks(db, chunk_ids, chunk_texts)
                await embedding_service.embed_and_store_concepts(db, concept_ids, concept_texts)
                logger.info(f"Embedded {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

                # === STEP 7: DONE ===
                await _update_status(db, sid, "ready")
                await db.commit()

                return {
                    "source_id": source_id,
                    "title": source.title,
                    "chunks_created": len(chunk_ids),
                    "concepts_created": len(concept_ids),
                    "lessons_generated": len(lesson_by_page),
                    "labs_generated": sum(1 for v in labs_by_page.values() if v is not None),
                    "status": "ready",
                }

            except Exception as e:
                logger.error(f"Ingestion failed for source {source_id}: {e}", exc_info=True)
                await _update_status(db, sid, "error", error_message=str(e))
                await db.commit()
                raise
    finally:
        await worker_engine.dispose()


def _create_extractor(source):
    """Create the appropriate extractor for a source."""
    from app.tools.extractors import get_extractor
    from app.config import get_settings
    settings = get_settings()
    whisper_kwargs = {
        "whisper_mode": settings.whisper_mode,
        "whisper_model": settings.whisper_model,
        "whisper_api_key": settings.whisper_api_key,
        "whisper_api_base_url": settings.whisper_api_base_url,
        "whisper_api_model": settings.whisper_api_model,
    }
    if source.type == "youtube":
        return get_extractor("youtube", **whisper_kwargs)
    elif source.type == "bilibili":
        kwargs = {**whisper_kwargs}
        sessdata = getattr(settings, "bilibili_sessdata", None)
        if sessdata:
            from bilibili_api import Credential
            kwargs["credential"] = Credential(
                sessdata=settings.bilibili_sessdata,
                bili_jct=getattr(settings, "bilibili_bili_jct", ""),
                buvid3=getattr(settings, "bilibili_buvid3", ""),
            )
        return get_extractor("bilibili", **kwargs)
    elif source.type == "pdf":
        return get_extractor("pdf")
    else:
        raise ValueError(f"Unsupported source type: {source.type}")


async def _update_status(db, source_id: UUID, status: str, error_message: str | None = None) -> None:
    """Update source status in the database."""
    from sqlalchemy import update as sa_update
    from app.db.models.source import Source

    if error_message:
        source = await db.get(Source, source_id)
        if source:
            source.metadata_ = {**source.metadata_, "error": error_message}
            source.status = status
            await db.flush()
            return

    await db.execute(
        sa_update(Source).where(Source.id == source_id).values(status=status)
    )
    await db.flush()


async def _get_or_create_concept(db, ext_concept):
    """Get existing concept by name/alias or create a new one."""
    from sqlalchemy import select
    from app.db.models.concept import Concept

    result = await db.execute(
        select(Concept).where(Concept.name == ext_concept.name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    for alias in ext_concept.aliases:
        result = await db.execute(
            select(Concept).where(Concept.name == alias)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    concept = Concept(
        name=ext_concept.name,
        description=ext_concept.description,
        category=ext_concept.category,
        aliases=ext_concept.aliases,
        prerequisites=[],
    )
    db.add(concept)
    await db.flush()
    return concept
