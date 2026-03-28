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
    soft_time_limit=1800,
    time_limit=1860,
)
def ingest_source(self, source_id: str) -> dict:
    """Main content ingestion pipeline task.

    Orchestrates: extract → analyze → store → embed.
    """
    import asyncio
    return asyncio.run(_ingest_source_async(self, source_id))


@celery_app.task(
    bind=True,
    name="content_ingestion.clone_source",
    max_retries=1,
    default_retry_delay=10,
    soft_time_limit=60,
    time_limit=90,
)
def clone_source(self, source_id: str, ref_source_id: str) -> dict:
    """Clone content from a ready ref_source to a new source. No LLM calls."""
    import asyncio
    return asyncio.run(_clone_source_async(self, source_id, ref_source_id))


async def _clone_source_async(task, source_id: str, ref_source_id: str) -> dict:
    """Async implementation of content cloning."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.concept import ConceptSource
    from app.config import get_settings

    settings = get_settings()
    worker_engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    worker_session_factory = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with worker_session_factory() as db:
            from uuid import UUID
            sid = UUID(source_id)
            ref_sid = UUID(ref_source_id)

            target = await db.get(Source, sid)
            ref = await db.get(Source, ref_sid)

            if not target or not ref or ref.status != "ready":
                if target:
                    target.status = "error"
                    target.metadata_ = {**target.metadata_, "error": "引用源不可用"}
                    await db.commit()
                return {"source_id": source_id, "status": "error", "reason": "ref_source not ready"}

            task.update_state(state="PROGRESS", meta={"stage": "cloning"})

            # Copy scalar fields
            target.title = target.title or ref.title
            target.raw_content = ref.raw_content
            target.metadata_ = {**ref.metadata_}
            await db.flush()

            # Clone ContentChunks
            result = await db.execute(
                select(ContentChunkModel).where(ContentChunkModel.source_id == ref_sid)
            )
            ref_chunks = result.scalars().all()
            chunk_count = 0
            for chunk in ref_chunks:
                new_chunk = ContentChunkModel(
                    source_id=sid,
                    text=chunk.text,
                    embedding=chunk.embedding,
                    metadata_=dict(chunk.metadata_),
                )
                db.add(new_chunk)
                chunk_count += 1
            await db.flush()

            # Clone ConceptSource links
            cs_result = await db.execute(
                select(ConceptSource).where(ConceptSource.source_id == ref_sid)
            )
            ref_concept_sources = cs_result.scalars().all()
            concept_count = 0
            for cs in ref_concept_sources:
                existing = await db.execute(
                    select(ConceptSource).where(
                        ConceptSource.concept_id == cs.concept_id,
                        ConceptSource.source_id == sid,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(ConceptSource(
                        concept_id=cs.concept_id,
                        source_id=sid,
                        context=cs.context,
                    ))
                    concept_count += 1
            await db.flush()

            # Mark ready
            target.status = "ready"
            await db.commit()

            logger.info(f"Cloned source {source_id} from ref {ref_source_id}: {chunk_count} chunks, {concept_count} concepts")
            return {
                "source_id": source_id,
                "ref_source_id": ref_source_id,
                "chunks_cloned": chunk_count,
                "concepts_linked": concept_count,
                "status": "ready",
            }
    finally:
        await worker_engine.dispose()


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

                whisper_kwargs = await _get_whisper_config(db, settings)
                bilibili_credential = (
                    await _get_bilibili_credential(db, settings)
                    if source.type == "bilibili"
                    else None
                )
                extractor = _create_extractor(source, whisper_kwargs, bilibili_credential)

                if source.type == "pdf":
                    from pathlib import Path
                    relative_path = source.metadata_.get("file_path", "")
                    file_path = str(Path(settings.upload_dir) / relative_path)
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
                cost_guard = CostGuard(db)

                # === STEP 2: ANALYZE ===
                await _update_status(db, sid, "analyzing")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
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

                # === STEP 3: STORE ===
                await _update_status(db, sid, "storing")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
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
                }
                await db.flush()
                logger.info(f"Stored {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

                # === STEP 4: EMBED ===
                await _update_status(db, sid, "embedding")
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
                    current_stage="embedding",
                )
                task.update_state(state="PROGRESS", meta={"stage": "embedding", "estimated_remaining_seconds": remaining})

                embedding_service = EmbeddingService(model_router)
                await embedding_service.embed_and_store_chunks(db, chunk_ids, chunk_texts)
                await embedding_service.embed_and_store_concepts(db, concept_ids, concept_texts)
                logger.info(f"Embedded {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

                # === STEP 5: DONE ===
                await _update_status(db, sid, "ready")
                await db.commit()

                # Notify waiting sources via Redis
                _publish_source_done(source, "ready")

                return {
                    "source_id": source_id,
                    "title": source.title,
                    "chunks_created": len(chunk_ids),
                    "concepts_created": len(concept_ids),
                    "status": "ready",
                }

            except Exception as e:
                logger.error(f"Ingestion failed for source {source_id}: {e}", exc_info=True)
                # Use a fresh session to update error status — the main session
                # may be in a broken transaction state after the failure.
                try:
                    async with worker_session_factory() as err_db:
                        await _update_status(err_db, sid, "error", error_message=str(e))
                except Exception as err_e:
                    logger.error(f"Failed to update error status for {source_id}: {err_e}")
                _publish_source_done(source, "error")
                raise
    finally:
        await worker_engine.dispose()


async def _get_whisper_config(db, settings) -> dict:
    """Get Whisper config from DB if available, else fall back to .env settings."""
    from sqlalchemy import select
    from app.db.models.whisper_config import WhisperConfig

    try:
        result = await db.execute(select(WhisperConfig).limit(1))
        config = result.scalar_one_or_none()
    except Exception:
        config = None

    if config and config.api_key_encrypted:
        from app.services.llm.encryption import decrypt_api_key
        api_key = decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key)
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


async def _get_bilibili_credential(db, settings):
    """Get Bilibili credential from DB if available, else fall back to .env."""
    from bilibili_api import Credential
    from sqlalchemy import select

    from app.db.models.bilibili_credential import BilibiliCredential
    from app.services.llm.encryption import decrypt_api_key

    try:
        result = await db.execute(select(BilibiliCredential).limit(1))
        bc = result.scalar_one_or_none()
        if bc and bc.sessdata_encrypted:
            sessdata = decrypt_api_key(bc.sessdata_encrypted, settings.llm_encryption_key)
            bili_jct = (
                decrypt_api_key(bc.bili_jct_encrypted, settings.llm_encryption_key)
                if bc.bili_jct_encrypted
                else ""
            )
            return Credential(sessdata=sessdata, bili_jct=bili_jct)
    except Exception:
        pass

    # Fallback to .env
    sessdata = getattr(settings, "bilibili_sessdata", "")
    if sessdata:
        return Credential(
            sessdata=sessdata,
            bili_jct=getattr(settings, "bilibili_bili_jct", ""),
            buvid3=getattr(settings, "bilibili_buvid3", ""),
        )
    return None


def _create_extractor(source, whisper_kwargs: dict, bilibili_credential=None):
    """Create the appropriate extractor for a source."""
    from app.tools.extractors import get_extractor

    if source.type == "youtube":
        return get_extractor("youtube", **whisper_kwargs)
    elif source.type == "bilibili":
        kwargs = {**whisper_kwargs}
        if bilibili_credential:
            kwargs["credential"] = bilibili_credential
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
            await db.commit()
            return

    await db.execute(
        sa_update(Source).where(Source.id == source_id).values(status=status)
    )
    await db.commit()


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


def _publish_source_done(source, status: str) -> None:
    """Publish source completion/failure event to Redis."""
    import json
    import redis
    from app.config import get_settings
    from app.services.content_key import content_key_hash

    if not source.content_key:
        return

    settings = get_settings()
    try:
        r = redis.Redis.from_url(settings.redis_url)
        channel = f"source:done:{content_key_hash(source.content_key)}"
        payload = json.dumps({"source_id": str(source.id), "status": status})
        r.publish(channel, payload)
        logger.info(f"Published {status} to {channel}")
    except Exception as e:
        logger.warning(f"Failed to publish source done event: {e}")
