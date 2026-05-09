"""Content ingestion Celery tasks."""

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.config import get_settings
from app.services.source_tasks import (
    TaskCancelledError,
    dispatch_course_generation,
    finish_source_processing_and_enqueue_course,
    mark_source_task,
    raise_if_cancelled,
    recover_course_generation_dispatch_failure,
)
from app.worker.celery_app import celery_app
from app.worker.resources import _create_worker_resources

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="content_ingestion.ingest_source",
    max_retries=2,
    default_retry_delay=30,
)
def ingest_source(self, source_id: str) -> dict:
    """Main content ingestion pipeline task.

    Orchestrates: extract -> analyze -> store -> embed.
    """
    import asyncio

    async def _runner():
        resources = _create_worker_resources()
        try:
            return await _ingest_source_async(self, source_id, resources)
        finally:
            await resources.engine.dispose()

    return asyncio.run(_runner())


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

    async def _runner():
        resources = _create_worker_resources()
        try:
            return await _clone_source_async(self, source_id, ref_source_id, resources)
        finally:
            await resources.engine.dispose()

    return asyncio.run(_runner())


async def _clone_source_async(
    task, source_id: str, ref_source_id: str, resources
) -> dict:
    """Async implementation of source cloning."""
    from sqlalchemy import select

    from app.db.models.concept import ConceptSource
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.source import Source

    sid = UUID(source_id)
    ref_sid = UUID(ref_source_id)

    async with resources.session_factory() as db:
        target = await db.get(Source, sid)
        ref = await db.get(Source, ref_sid)
        completion = None

        if not target or not ref or ref.status != "ready":
            if target:
                await _update_status(db, sid, "error", error_message="引用源不可用")
                await db.commit()
            return {
                "source_id": source_id,
                "status": "error",
                "reason": "ref_source_not_ready",
            }

        # Idempotency: redelivered clone for an already-ready target.
        if target.status == "ready":
            logger.info(
                "Skipping clone for source %s: already ready", source_id
            )
            return {
                "source_id": source_id,
                "status": "ready",
                "skipped": True,
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

            completion = await finish_source_processing_and_enqueue_course(
                db=db,
                source=target,
                processing_task=await _get_source_processing_task(db, sid),
                payload={
                    "source_id": source_id,
                    "ref_source_id": ref_source_id,
                    "chunks_cloned": chunk_count,
                    "concepts_linked": concept_count,
                },
            )
            await db.commit()

            logger.info(
                "Cloned source %s from donor %s: %s chunks, %s concepts",
                source_id,
                ref_source_id,
                chunk_count,
                concept_count,
            )
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
    if completion is None:
        raise RuntimeError("Clone finished without preparing course generation")
    try:
        dispatch_course_generation(
            payload=completion.course_dispatch.payload,
            task_id=completion.course_dispatch.task_id,
            user_id=completion.course_dispatch.user_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to dispatch course generation for cloned source %s: %s",
            source_id,
            exc,
            exc_info=True,
        )
        await recover_course_generation_dispatch_failure(
            session_factory=resources.session_factory,
            source_id=sid,
            course_task_id=completion.course_dispatch.task_id,
            fallback_task_id=completion.course_dispatch.fallback_task_id,
            error_message=str(exc),
        )
        raise RuntimeError(f"Failed to dispatch course generation: {exc}") from exc
    return completion.result


async def _ingest_source_async(task, source_id: str, resources) -> dict:
    """Async implementation of the ingestion pipeline."""
    from sqlalchemy import select

    from app.db.models.concept import Concept, ConceptSource
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.source import Source
    from app.services.content_analyzer import ContentAnalyzer
    from app.services.embedding import EmbeddingService
    from app.services.teaching_asset_planner import TeachingAssetPlanner

    sid = UUID(source_id)

    async with resources.session_factory() as db:
        source = await db.get(Source, sid)
        completion = None
        if not source:
            raise ValueError(f"Source {source_id} not found")

        # Idempotency: a redelivered task (acks_late) for an already-ready
        # source should short-circuit instead of re-extracting and inserting
        # duplicate chunks/concepts.
        if source.status == "ready":
            logger.info(
                "Skipping ingest for source %s: already ready", source_id
            )
            return {
                "source_id": source_id,
                "status": "ready",
                "skipped": True,
            }

        try:
            # === STEP 1: EXTRACT ===
            await raise_if_cancelled(db, source_id=sid, task_type="source_processing")
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
            await raise_if_cancelled(db, source_id=sid, task_type="source_processing")
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

            planner = TeachingAssetPlanner()
            asset_plan = planner.plan(
                source_title=source.title or "Untitled",
                source_type=source.type,
                overall_summary=analysis.overall_summary,
                chunk_topics=[chunk.topic for chunk in analysis.chunks],
                has_code=any(chunk.has_code for chunk in analysis.chunks),
            )

            # Lesson/lab/graph generation now lives in course_generator.
            # Ingest only produces the content fingerprint (chunks + concepts +
            # embeddings + analysis); teaching assets are course-level.

            # === STEP 5: STORE ===
            await raise_if_cancelled(db, source_id=sid, task_type="source_processing")
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
                "asset_plan": asset_plan.model_dump(),
            }
            await db.flush()
            logger.info(
                "Stored %s chunks and %s concepts",
                len(chunk_ids),
                len(concept_ids),
            )

            # === STEP 6: EMBED ===
            await raise_if_cancelled(db, source_id=sid, task_type="source_processing")
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
            completion = await finish_source_processing_and_enqueue_course(
                db=db,
                source=source,
                processing_task=await _get_source_processing_task(db, sid),
                payload={
                    "source_id": source_id,
                    "title": source.title,
                    "chunks_created": len(chunk_ids),
                    "concepts_created": len(concept_ids),
                },
            )
            await db.commit()
        except TaskCancelledError:
            logger.info("Ingestion cancelled for source %s", source_id)
            await _mark_source_cancelled(resources.session_factory, sid)
            return {"source_id": source_id, "status": "cancelled"}
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
    if completion is None:
        raise RuntimeError("Ingestion finished without preparing course generation")
    try:
        dispatch_course_generation(
            payload=completion.course_dispatch.payload,
            task_id=completion.course_dispatch.task_id,
            user_id=completion.course_dispatch.user_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to dispatch course generation for source %s: %s",
            source_id,
            exc,
            exc_info=True,
        )
        await recover_course_generation_dispatch_failure(
            session_factory=resources.session_factory,
            source_id=sid,
            course_task_id=completion.course_dispatch.task_id,
            fallback_task_id=completion.course_dispatch.fallback_task_id,
            error_message=str(exc),
        )
        raise RuntimeError(f"Failed to dispatch course generation: {exc}") from exc
    return completion.result


async def _get_bilibili_credential(db):
    """Load a stored Bilibili credential, falling back to environment variables."""
    from app.services.bilibili_credential import load_bilibili_credential

    return await load_bilibili_credential(db)


async def _get_whisper_config(db) -> dict:
    """Load Whisper ASR config from DB, falling back to environment settings."""
    from sqlalchemy import select

    from app.db.models.whisper_config import WhisperConfig
    from app.services.llm.encryption import decrypt_api_key_or_none

    settings = get_settings()

    try:
        result = await db.execute(select(WhisperConfig).limit(1))
        config = result.scalar_one_or_none()
    except Exception:
        config = None

    if config:
        api_key = decrypt_api_key_or_none(
            config.api_key_encrypted,
            settings.llm_encryption_key,
        )
        if config.api_key_encrypted and api_key is None:
            logger.warning(
                "Failed to decrypt stored Whisper API key; falling back to env/default for ingestion."
            )
        return {
            "whisper_mode": config.mode or settings.whisper_mode,
            "whisper_model": config.local_model or settings.whisper_model,
            "whisper_api_key": api_key or settings.whisper_api_key,
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


async def _update_status(
    db,
    source_id: UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update source and source-task lifecycle state in the database."""

    from sqlalchemy import select

    from app.db.models.source import Source
    from app.db.models.source_task import SourceTask

    task_status, stage, task_error_summary = _source_task_lifecycle(
        status, error_message
    )

    source = await db.get(Source, source_id)
    if source:
        source.status = status
        if error_message:
            source.metadata_ = {**source.metadata_, "error": error_message}

    result = await db.execute(
        select(SourceTask)
        .where(
            SourceTask.source_id == source_id,
            SourceTask.task_type == "source_processing",
        )
        .order_by(SourceTask.created_at.desc())
        .limit(1)
    )
    source_task = result.scalar_one_or_none()
    if source_task:
        await mark_source_task(
            db,
            source_id=source_id,
            task_type="source_processing",
            status=task_status,
            stage=stage,
            error_summary=task_error_summary,
        )

    # Commit per stage so /sources/{id}/progress sees mid-pipeline transitions.
    # Data writes (chunks, embeddings, etc.) live in their own commit at the
    # end of each stage block.
    await db.commit()


def _source_task_lifecycle(
    status: str,
    error_message: str | None = None,
) -> tuple[str, str, str | None]:
    """Map source status into persisted task lifecycle fields."""
    if status == "pending":
        return "pending", "pending", None
    if status == "ready":
        return "success", "ready", None
    if status == "error":
        return "failure", "error", error_message
    if status == "cancelled":
        return "cancelled", "cancelled", None
    return "running", status, None


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


async def _mark_source_cancelled(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: UUID,
) -> None:
    """Persist a cancelled state using a fresh session."""
    try:
        async with session_factory() as db:
            await _update_status(db, source_id, "cancelled")
            await db.commit()
    except Exception:
        logger.error(
            "Failed to persist cancelled status for source %s",
            source_id,
            exc_info=True,
        )


async def _get_source_processing_task(
    db: AsyncSession,
    source_id: UUID,
):
    """Load the persisted source_processing task row, if present."""
    from sqlalchemy import select

    from app.db.models.source_task import SourceTask

    result = await db.execute(
        select(SourceTask).where(
            SourceTask.source_id == source_id,
            SourceTask.task_type == "source_processing",
        )
    )
    return result.scalar_one_or_none()


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
