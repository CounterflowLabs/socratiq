"""Content ingestion Celery tasks."""

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.services.llm.router import ModelRouter
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResources:
    """Loop-local resources for a single Celery task run."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    model_router: ModelRouter


def _create_worker_resources() -> WorkerResources:
    """Create a fresh async engine/session factory/router for the current loop."""
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    model_router = ModelRouter(
        session_factory=session_factory,
        encryption_key=settings.llm_encryption_key,
    )
    return WorkerResources(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        model_router=model_router,
    )


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

    Orchestrates: extract -> analyze -> store -> embed.
    """
    import asyncio

    return asyncio.run(_ingest_source_async(self, source_id))


@celery_app.task(
    bind=True,
    name="content_ingestion.clone_source",
    max_retries=1,
    default_retry_delay=10,
    soft_time_limit=120,
    time_limit=150,
)
def clone_source(self, source_id: str, ref_source_id: str) -> dict:
    """Clone already extracted content from a ready donor source."""
    import asyncio

    return asyncio.run(_clone_source_async(self, source_id, ref_source_id))


async def _clone_source_async(task, source_id: str, ref_source_id: str) -> dict:
    """Async implementation of source cloning."""
    from sqlalchemy import select

    from app.db.models.concept import ConceptSource
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.source import Source

    resources = _create_worker_resources()
    sid = UUID(source_id)
    ref_sid = UUID(ref_source_id)

    try:
        async with resources.session_factory() as db:
            target = await db.get(Source, sid)
            ref = await db.get(Source, ref_sid)

            if not target or not ref or ref.status != "ready":
                if target:
                    await _update_status(db, sid, "error", error_message="引用源不可用")
                    await db.commit()
                return {
                    "source_id": source_id,
                    "status": "error",
                    "reason": "ref_source_not_ready",
                }
            try:
                task.update_state(state="PROGRESS", meta={"stage": "cloning"})
                await _update_status(db, sid, "storing")

                ref_metadata = dict(ref.metadata_ or {})
                ref_metadata.pop("course_id", None)
                ref_metadata.pop("error", None)
                target.title = target.title or ref.title
                target.raw_content = ref.raw_content
                target.metadata_ = {
                    **ref_metadata,
                    **(target.metadata_ or {}),
                    "reused_from_source_id": str(ref.id),
                }
                await db.flush()

                result = await db.execute(
                    select(ContentChunkModel).where(ContentChunkModel.source_id == ref_sid)
                )
                ref_chunks = result.scalars().all()
                chunk_count = 0
                for chunk in ref_chunks:
                    db.add(
                        ContentChunkModel(
                            source_id=sid,
                            text=chunk.text,
                            embedding=chunk.embedding,
                            metadata_=dict(chunk.metadata_ or {}),
                        )
                    )
                    chunk_count += 1

                cs_result = await db.execute(
                    select(ConceptSource).where(ConceptSource.source_id == ref_sid)
                )
                ref_concept_sources = cs_result.scalars().all()
                concept_count = 0
                for cs in ref_concept_sources:
                    db.add(
                        ConceptSource(
                            concept_id=cs.concept_id,
                            source_id=sid,
                            context=cs.context,
                        )
                    )
                    concept_count += 1

                await _update_status(db, sid, "assembling_course")
                task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})
                course_id = await _assemble_course_for_source(
                    db,
                    source=target,
                    model_router=resources.model_router,
                )

                await _update_status(db, sid, "ready")
                await db.commit()

                logger.info(
                    "Cloned source %s from donor %s: %s chunks, %s concepts",
                    source_id,
                    ref_source_id,
                    chunk_count,
                    concept_count,
                )
                return {
                    "source_id": source_id,
                    "ref_source_id": ref_source_id,
                    "chunks_cloned": chunk_count,
                    "concepts_linked": concept_count,
                    "course_id": course_id,
                    "status": "ready",
                }
            except Exception as exc:
                logger.error(
                    "Clone ingestion failed for source %s: %s",
                    source_id,
                    exc,
                    exc_info=True,
                )
                await _update_status(db, sid, "error", error_message=str(exc))
                await db.commit()
                raise
    finally:
        await resources.engine.dispose()


async def _ingest_source_async(task, source_id: str) -> dict:
    """Async implementation of the ingestion pipeline."""
    from sqlalchemy import select

    from app.db.models.concept import Concept, ConceptSource
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.source import Source
    from app.services.content_analyzer import ContentAnalyzer
    from app.services.embedding import EmbeddingService

    resources = _create_worker_resources()
    sid = UUID(source_id)

    try:
        async with resources.session_factory() as db:
            source = await db.get(Source, sid)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            try:
                # === STEP 1: EXTRACT ===
                await _update_status(db, sid, "extracting")
                task.update_state(state="PROGRESS", meta={"stage": "extracting"})

                whisper_kwargs = await _get_whisper_config(db)
                bilibili_credential = None
                if source.type == "bilibili":
                    bilibili_credential = await _get_bilibili_credential(db)

                extractor = _create_extractor(
                    source,
                    whisper_kwargs=whisper_kwargs,
                    bilibili_credential=bilibili_credential,
                )

                if source.type == "pdf":
                    relative_path = source.metadata_.get("file_path", "")
                    file_path = str(Path(resources.settings.upload_dir) / relative_path)
                    result = await extractor.extract(file_path)
                else:
                    result = await extractor.extract(source.url or "")

                source.title = source.title or result.title
                source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)
                source.metadata_ = {**source.metadata_, **result.metadata}
                await db.flush()
                logger.info("Extracted %s chunks from source %s", len(result.chunks), source_id)

                # === STEP 2: ANALYZE ===
                await _update_status(db, sid, "analyzing")
                task.update_state(state="PROGRESS", meta={"stage": "analyzing"})

                analyzer = ContentAnalyzer(resources.model_router)
                analysis = await analyzer.analyze(
                    title=source.title or "Untitled",
                    chunks=result.chunks,
                    source_type=source.type,
                )
                logger.info(
                    "Analyzed source %s: %s concepts, %s chunks",
                    source_id,
                    len(analysis.concepts),
                    len(analysis.chunks),
                )

                # === STEP 3: GENERATE LESSONS ===
                await _update_status(db, sid, "generating_lessons")
                task.update_state(state="PROGRESS", meta={"stage": "generating_lessons"})

                from app.services.lesson_generator import LessonGenerator
                from app.services.llm.router import TaskType

                lesson_provider = await resources.model_router.get_provider(
                    TaskType.CONTENT_ANALYSIS
                )
                lesson_gen = LessonGenerator(lesson_provider)

                page_groups: dict[int, list] = {}
                for chunk in analysis.chunks:
                    page_idx = chunk.metadata.get("page_index", 0)
                    page_groups.setdefault(page_idx, []).append(chunk)

                lesson_by_page: dict[int, object] = {}
                for page_idx in sorted(page_groups.keys()):
                    page_chunks = page_groups[page_idx]
                    chunk_texts = [c.raw_text for c in page_chunks]
                    page_title = (
                        page_chunks[0].metadata.get("page_title")
                        or source.title
                        or "Untitled"
                    )
                    lesson_content = await lesson_gen.generate(chunk_texts, page_title)
                    lesson_by_page[page_idx] = lesson_content
                    logger.info(
                        "Generated lesson for page %s: %s sections",
                        page_idx,
                        len(lesson_content.sections),
                    )

                # === STEP 4: GENERATE LABS ===
                await _update_status(db, sid, "generating_labs")
                task.update_state(state="PROGRESS", meta={"stage": "generating_labs"})

                from app.db.models.lab import Lab
                from app.services.lab_generator import LabGenerator

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
                    for snippet in all_snippets:
                        lang_counts[snippet.language] = (
                            lang_counts.get(snippet.language, 0) + 1
                        )
                    language = max(lang_counts, key=lang_counts.__getitem__)

                    lab_result = await lab_gen.generate(
                        code_snippets=all_snippets,
                        lesson_context=lesson_content.summary,
                        language=language,
                    )
                    labs_by_page[page_idx] = lab_result
                    if lab_result:
                        logger.info(
                            "Generated lab for page %s: %s",
                            page_idx,
                            lab_result.get("title"),
                        )
                    else:
                        logger.info(
                            "No lab generated for page %s (low confidence or error)",
                            page_idx,
                        )

                # === STEP 5: STORE ===
                await _update_status(db, sid, "storing")
                task.update_state(state="PROGRESS", meta={"stage": "storing"})

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
                logger.info(
                    "Stored %s chunks and %s concepts",
                    len(chunk_ids),
                    len(concept_ids),
                )

                # === STEP 6: EMBED ===
                await _update_status(db, sid, "embedding")
                task.update_state(state="PROGRESS", meta={"stage": "embedding"})

                embedding_service = EmbeddingService(resources.model_router)
                await embedding_service.embed_and_store_chunks(db, chunk_ids, chunk_texts)
                await embedding_service.embed_and_store_concepts(
                    db, concept_ids, concept_texts
                )
                logger.info(
                    "Embedded %s chunks and %s concepts",
                    len(chunk_ids),
                    len(concept_ids),
                )

                # === STEP 7: DONE ===
                await _update_status(db, sid, "assembling_course")
                task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})
                course_id = await _assemble_course_for_source(
                    db,
                    source=source,
                    model_router=resources.model_router,
                )

                await _update_status(db, sid, "ready")
                await db.commit()

                return {
                    "source_id": source_id,
                    "title": source.title,
                    "chunks_created": len(chunk_ids),
                    "concepts_created": len(concept_ids),
                    "lessons_generated": len(lesson_by_page),
                    "labs_generated": sum(
                        1 for lab_data in labs_by_page.values() if lab_data is not None
                    ),
                    "course_id": course_id,
                    "status": "ready",
                }
            except Exception as exc:
                logger.error(
                    "Ingestion failed for source %s: %s",
                    source_id,
                    exc,
                    exc_info=True,
                )
                await _mark_source_error(
                    resources.session_factory,
                    sid,
                    str(exc),
                )
                raise
    finally:
        await resources.engine.dispose()


async def _get_bilibili_credential(db):
    """Load a stored Bilibili credential, falling back to environment variables."""
    from bilibili_api import Credential
    from sqlalchemy import select

    from app.db.models.bilibili_credential import BilibiliCredential
    from app.services.llm.encryption import decrypt_api_key

    settings = get_settings()

    try:
        result = await db.execute(select(BilibiliCredential).limit(1))
        stored = result.scalar_one_or_none()
        if stored and stored.sessdata_encrypted:
            sessdata = decrypt_api_key(
                stored.sessdata_encrypted,
                settings.llm_encryption_key,
            )
            bili_jct = (
                decrypt_api_key(
                    stored.bili_jct_encrypted,
                    settings.llm_encryption_key,
                )
                if stored.bili_jct_encrypted
                else ""
            )
            return Credential(sessdata=sessdata, bili_jct=bili_jct)
    except Exception:
        logger.warning(
            "Failed to load stored Bilibili credential; falling back to env.",
            exc_info=True,
        )

    sessdata = getattr(settings, "bilibili_sessdata", "")
    if sessdata:
        return Credential(
            sessdata=sessdata,
            bili_jct=getattr(settings, "bilibili_bili_jct", ""),
            buvid3=getattr(settings, "bilibili_buvid3", ""),
        )

    return None


async def _get_whisper_config(db) -> dict:
    """Load Whisper ASR config from DB, falling back to environment settings."""
    from sqlalchemy import select

    from app.db.models.whisper_config import WhisperConfig
    from app.services.llm.encryption import decrypt_api_key

    settings = get_settings()

    try:
        result = await db.execute(select(WhisperConfig).limit(1))
        config = result.scalar_one_or_none()
    except Exception:
        config = None

    if config:
        api_key = (
            decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key)
            if config.api_key_encrypted
            else settings.whisper_api_key
        )
        return {
            "whisper_mode": config.mode or settings.whisper_mode,
            "whisper_model": config.local_model or settings.whisper_model,
            "whisper_api_key": api_key,
            "whisper_api_base_url": config.api_base_url or settings.whisper_api_base_url,
            "whisper_api_model": config.api_model or settings.whisper_api_model,
        }

    return {
        "whisper_mode": settings.whisper_mode,
        "whisper_model": settings.whisper_model,
        "whisper_api_key": settings.whisper_api_key,
        "whisper_api_base_url": settings.whisper_api_base_url,
        "whisper_api_model": settings.whisper_api_model,
    }


def _create_extractor(source, whisper_kwargs: dict, bilibili_credential=None):
    """Create the appropriate extractor for a source."""
    from app.tools.extractors import get_extractor

    if source.type == "youtube":
        return get_extractor("youtube", **whisper_kwargs)
    if source.type == "bilibili":
        kwargs = {**whisper_kwargs}
        if bilibili_credential:
            kwargs["credential"] = bilibili_credential
        return get_extractor("bilibili", **kwargs)
    if source.type == "pdf":
        return get_extractor("pdf")
    raise ValueError(f"Unsupported source type: {source.type}")


async def _assemble_course_for_source(
    db: AsyncSession,
    source,
    model_router: ModelRouter,
) -> str:
    """Create the course for a fully processed source and return its ID."""
    from app.services.course_generator import CourseGenerator

    generator = CourseGenerator(model_router)
    course = await generator.generate(
        db=db,
        source_ids=[source.id],
        title=source.title,
        user_id=source.created_by,
        skip_ready_check=True,
    )
    source.metadata_ = {
        **(source.metadata_ or {}),
        "course_id": str(course.id),
    }
    await db.flush()
    return str(course.id)


async def _update_status(
    db,
    source_id: UUID,
    status: str,
    error_message: str | None = None,
) -> None:
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


async def _mark_source_error(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
    error_message: str,
) -> None:
    """Persist an error state using a fresh session after task failure."""
    try:
        async with session_factory() as db:
            await _update_status(db, source_id, "error", error_message=error_message)
            await db.commit()
    except Exception:
        logger.error(
            "Failed to persist error status for source %s",
            source_id,
            exc_info=True,
        )


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
