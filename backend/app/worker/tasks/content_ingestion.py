"""Content ingestion Celery tasks."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.agentcore.events import (
    EventBus,
    RedisEventSink,
    TracerEventSink,
    run_error,
    run_finished,
    run_started,
    state_snapshot,
    tool_activity,
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
from app.worker._compat import task_shim

logger = logging.getLogger(__name__)

# 60-minute TTL guards against worker death without a release — long enough
# for the slowest realistic ingest (large PDFs, full Whisper transcription)
# yet short enough that a stuck lock self-clears within an hour.
INGEST_LOCK_TTL_SECONDS = 60 * 60


@asynccontextmanager
async def _ingest_lock(source_id: str):
    """Acquire a per-source distributed lock via Redis SET NX EX.

    Yields ``True`` on success and ``False`` if another worker holds the
    lock. The lock is released in ``finally`` so success, exception, and
    cancellation paths all unlock. We use a per-acquisition token so a
    redelivered/late worker doesn't release a lock owned by a fresher run.
    """
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url)
    key = f"ingest_lock:{source_id}"
    token = uuid_token()
    try:
        acquired = await client.set(key, token, nx=True, ex=INGEST_LOCK_TTL_SECONDS)
        try:
            yield bool(acquired)
        finally:
            if acquired:
                # Compare-and-delete so we never release someone else's lock
                # if our run somehow outlived the TTL.
                stored = await client.get(key)
                stored_str = stored.decode() if isinstance(stored, bytes) else stored
                if stored_str == token:
                    await client.delete(key)
    finally:
        await client.aclose()


def uuid_token() -> str:
    """Generate an opaque per-acquisition token."""
    from uuid import uuid4

    return uuid4().hex


@asynccontextmanager
async def _ingestion_run(ctx: dict, source_id: str):
    """Wrap an ingestion task in an AG-UI run.

    Emits ``RUN_STARTED`` up front, ``RUN_FINISHED`` on success / ``RUN_ERROR``
    on failure, and yields the ``EventBus`` so the pipeline can publish per-stage
    ``STATE_SNAPSHOT`` events. ``run_id`` is the ARQ job id — the same id the
    frontend holds as the processing task id — so the web SSE endpoint streams it
    to the browser (replacing polling). Best-effort: this is the live-progress
    channel, never the source of truth.
    """
    run_id = ctx.get("job_id") or source_id
    redis = aioredis.from_url(get_settings().redis_url)
    bus = EventBus(
        thread_id=source_id,
        run_id=run_id,
        sinks=[RedisEventSink(redis, run_id), TracerEventSink()],
    )
    await bus.emit(run_started(thread_id=source_id, run_id=run_id))
    try:
        yield bus
    except Exception as exc:  # noqa: BLE001
        await bus.emit(run_error(message=str(exc)))
        raise
    else:
        await bus.emit(run_finished(thread_id=source_id, run_id=run_id))
    finally:
        await bus.aclose()
        await redis.aclose()


async def ingest_source(ctx: dict, source_id: str) -> dict:
    """Main content ingestion pipeline task (extract → analyze → store → embed)."""
    async with _ingestion_run(ctx, source_id) as bus:
        return await _ingest_source_async(
            task_shim(ctx), source_id, ctx["resources"], event_bus=bus
        )


async def clone_source(ctx: dict, source_id: str, ref_source_id: str) -> dict:
    """Clone already extracted content from a ready donor source."""
    async with _ingestion_run(ctx, source_id) as bus:
        return await _clone_source_async(
            task_shim(ctx), source_id, ref_source_id, ctx["resources"], event_bus=bus
        )


async def _clone_source_async(
    task, source_id: str, ref_source_id: str, resources, event_bus=None
) -> dict:
    """Async implementation of source cloning."""
    sid = UUID(source_id)
    ref_sid = UUID(ref_source_id)

    async with _ingest_lock(source_id) as acquired:
        if not acquired:
            logger.info(
                "Skipping clone for source %s: another worker holds the lock",
                source_id,
            )
            return {"source_id": source_id, "status": "skipped_locked"}
        return await _clone_source_locked(
            task, source_id, ref_source_id, resources, sid, ref_sid, event_bus=event_bus
        )


async def _clone_source_locked(
    task,
    source_id: str,
    ref_source_id: str,
    resources,
    sid: UUID,
    ref_sid: UUID,
    event_bus=None,
) -> dict:
    """Locked clone body. Extracted so the lock wrapper stays small."""
    from sqlalchemy import select

    from app.db.models.concept import ConceptSource
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.source import Source

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
            await _update_status(db, sid, "storing", event_bus=event_bus)

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
        await dispatch_course_generation(
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


async def _ingest_source_async(task, source_id: str, resources, event_bus=None) -> dict:
    """Async implementation of the ingestion pipeline."""
    async with _ingest_lock(source_id) as acquired:
        if not acquired:
            logger.info(
                "Skipping ingest for source %s: another worker holds the lock",
                source_id,
            )
            return {"source_id": source_id, "status": "skipped_locked"}
        return await _ingest_source_locked(task, source_id, resources, event_bus=event_bus)


async def _ingest_source_locked(task, source_id: str, resources, event_bus=None) -> dict:
    """Locked ingest body. Extracted so the lock wrapper stays small."""
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
            await _update_status(db, sid, "extracting", event_bus=event_bus)
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

            async with tool_activity(
                event_bus,
                f"extract.{source.type}",
                args={"url": source.url} if source.url else None,
            ) as act:
                if source.type == "pdf":
                    relative_path = source.metadata_.get("file_path", "")
                    file_path = str(Path(resources.settings.upload_dir) / relative_path)
                    result = await extractor.extract(file_path)
                else:
                    result = await extractor.extract(source.url or "")
                act.set(f"{len(result.chunks)} 段内容")

            source.title = source.title or result.title
            source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)
            source.metadata_ = {**source.metadata_, **result.metadata}
            await db.flush()
            logger.info("Extracted %s chunks from source %s", len(result.chunks), source_id)

            # === STEP 2: ANALYZE ===
            await raise_if_cancelled(db, source_id=sid, task_type="source_processing")
            await _update_status(db, sid, "analyzing", event_bus=event_bus)
            task.update_state(state="PROGRESS", meta={"stage": "analyzing"})

            analyzer = ContentAnalyzer(resources.model_router)
            async with tool_activity(
                event_bus, "analyze.content", args={"chunks": len(result.chunks)}
            ) as act:
                analysis = await analyzer.analyze(
                    title=source.title or "Untitled",
                    chunks=result.chunks,
                    source_type=source.type,
                )
                act.set(
                    f"{len(analysis.concepts)} 个概念 · {len(analysis.chunks)} 段"
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
            await _update_status(db, sid, "storing", event_bus=event_bus)
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

            # The LLM emits prerequisites as concept names (per the contract
            # in prompts/content_analysis.md). The Concept.prerequisites
            # column stores UUIDs, so we resolve names -> ids in a second
            # pass once every concept has been upserted and has an id. This
            # is what populates the edges in /knowledge-graph; without it
            # the graph endpoint returns nodes only.
            await _resolve_concept_prerequisites(db, analysis.concepts, concept_ids)

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
            await _update_status(db, sid, "embedding", event_bus=event_bus)
            task.update_state(state="PROGRESS", meta={"stage": "embedding"})

            # Embeddings are an ENHANCEMENT (RAG retrieval + the section
            # floor's boundary hints at course-generation time), not a
            # prerequisite for producing a course. If the embedding provider
            # is unavailable (e.g. a local Ollama sidecar is down), degrade
            # gracefully: log, skip vectors, and continue. The generation-time
            # planner tolerates missing vectors (boundary hints collapse to
            # zero and it coarsens by size) and downstream RAG simply has no
            # vectors for this source — both far better than failing the
            # whole ingestion.
            embedding_service = EmbeddingService(resources.model_router)
            try:
                async with tool_activity(
                    event_bus,
                    "embed.vectors",
                    args={"chunks": len(chunk_ids), "concepts": len(concept_ids)},
                ) as act:
                    await embedding_service.embed_and_store_chunks(
                        db, chunk_ids, chunk_texts
                    )
                    await embedding_service.embed_and_store_concepts(
                        db, concept_ids, concept_texts
                    )
                    act.set(f"{len(chunk_ids)} 块 · {len(concept_ids)} 概念")
                logger.info(
                    "Embedded %s chunks and %s concepts",
                    len(chunk_ids),
                    len(concept_ids),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Embedding step failed for source %s; continuing without "
                    "vectors (RAG + section boundary hints degraded): %s",
                    source_id,
                    exc,
                )

            # Section planning moved to course generation (see
            # ``course_generator.ensure_section_buckets``): bucketing is a
            # course-level decision, and ingestion's output is only the
            # content fingerprint (chunks + concepts + embeddings + analysis).

            # === STEP 6.6: REFERENCE FETCH + RANK (arXiv, best-effort) ===
            # Turn the source's top concepts into real, citable references and
            # cache them so lessons' ``further_reading`` cites fetched papers
            # (verified URLs) rather than model memory. arXiv search is
            # high-recall / low-precision, so an LLM precision pass
            # (ReferenceRanker) drops off-topic candidates and keeps only
            # genuinely relevant, authoritative ones. Any failure (network,
            # rate-limit, no relevant results) leaves references empty and never
            # blocks ingestion; lessons then fall back to model-known classics.
            if get_settings().reference_search_enabled:
                try:
                    from app.services.llm import TaskType as _RefTaskType
                    from app.services.reference_fetcher import (
                        ReferenceRanker,
                        build_reference_fetcher,
                    )
                    from app.services.research_enrichment import FETCHED_REFERENCES_KEY

                    fetcher = build_reference_fetcher(
                        enabled=True,
                        semantic_scholar_api_key=get_settings().semantic_scholar_api_key,
                    )
                    concept_names = [c.name for c in analysis.concepts if c.name][:4]
                    candidates = []
                    seen: set[str] = set()
                    ranked = []
                    async with tool_activity(
                        event_bus, "references.search", args={"concepts": concept_names}
                    ) as act:
                        if fetcher is not None:
                            for name in concept_names:
                                for card in await fetcher.fetch(
                                    name, concepts=[name], max_results=5
                                ):
                                    key = (card.url or card.title).strip().lower()
                                    if key in seen:
                                        continue
                                    seen.add(key)
                                    candidates.append(card)
                        if candidates:
                            topic = f"{source.title or ''}。{analysis.overall_summary or ''}".strip("。")
                            rank_provider = await resources.model_router.get_provider(
                                _RefTaskType.CONTENT_ANALYSIS
                            )
                            ranked = await ReferenceRanker(rank_provider).rank(
                                topic=topic, candidates=candidates, keep=6
                            )
                        act.set(f"{len(candidates)} 候选 → 保留 {len(ranked)}")
                    if ranked:
                        source.metadata_ = {
                            **(source.metadata_ or {}),
                            FETCHED_REFERENCES_KEY: [
                                c.model_dump(exclude_none=True) for c in ranked
                            ],
                        }
                        await db.flush()
                        logger.info(
                            "References: %d candidates -> kept %d for source %s",
                            len(candidates),
                            len(ranked),
                            source_id,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Reference fetch/rank failed for source %s: %s", source_id, exc
                    )

            # Stamp the embed-model identity so a later model upgrade can
            # mark this source as ``stale`` (PRD §3).
            from app.services.embedding import current_embedding_model_id

            embed_model_id = await current_embedding_model_id(resources.model_router)
            if embed_model_id:
                source.metadata_ = {
                    **(source.metadata_ or {}),
                    "embed_model": embed_model_id,
                    "chunks": len(chunk_ids),
                    "vectors": len(chunk_ids) + len(concept_ids),
                }

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
        await dispatch_course_generation(
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
    event_bus=None,
) -> None:
    """Update source and source-task lifecycle state in the database.

    When ``event_bus`` is provided, also publishes a ``STATE_SNAPSHOT`` for the
    new stage so the web SSE endpoint can stream live ingestion progress. The
    DB write is authoritative; the emit is best-effort and never raised.
    """

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

    # AG-UI live progress: snapshot the new stage for the SSE channel. Best
    # effort — a Redis hiccup must never break ingestion.
    if event_bus is not None:
        try:
            await event_bus.emit(
                state_snapshot(
                    {
                        "phase": "source_processing",
                        "stage": stage,
                        "status": task_status,
                    }
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("ingestion progress emit failed", exc_info=True)


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
        select(SourceTask)
        .where(
            SourceTask.source_id == source_id,
            SourceTask.task_type == "source_processing",
        )
        .order_by(SourceTask.created_at.desc())
        .limit(1)
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


async def _resolve_concept_prerequisites(
    db,
    ext_concepts,
    concept_ids,
) -> int:
    """Resolve LLM-emitted prerequisite names into ``Concept.prerequisites`` UUIDs.

    The content-analysis prompt requires every entry of ``prerequisites`` to
    be a ``name`` that also appears in the same ``concepts[]`` payload. We
    enforce that contract here and use the resulting in-memory name->id map
    to update ``Concept.prerequisites`` in Postgres. Aliases of each
    concept also resolve to the same id so the LLM can refer to a prereq
    by any of its known surface forms.

    Merging is union-style: re-ingesting a concept from a second source
    adds new prereqs without losing the ones learned from the first source.
    Self-references (a concept listing itself as a prereq) are dropped, as
    are unknown names. Two-node cycles (``A -> B -> A``) are prevented by
    checking the other concept's existing prereq list before insertion;
    longer cycles are not detected here because the prompt forbids them
    and the run-time cost of a full DFS isn't worth it for typical 3-15
    concept analyses.

    Args:
        db: Async SQLAlchemy session inside the ingestion transaction.
        ext_concepts: Parallel list of ``ExtractedConcept`` objects (from
            ``ContentAnalyzer``). Same length and order as ``concept_ids``.
        concept_ids: Parallel list of ``Concept.id`` UUIDs.

    Returns:
        The number of concepts whose ``prerequisites`` column was updated.
        Callers can use this to decide whether to emit a log line.
    """
    from sqlalchemy import select, update

    from app.db.models.concept import Concept

    if len(ext_concepts) != len(concept_ids):
        raise ValueError("ext_concepts and concept_ids must be the same length")

    # Build a name + alias -> id map scoped to *this* analysis. The prompt
    # contract says prereqs only refer to local names, so we deliberately
    # don't fall back to a global concept lookup — that would let unrelated
    # concepts from other domains pollute the graph.
    name_to_id: dict[str, UUID] = {}
    for ext_concept, cid in zip(ext_concepts, concept_ids):
        name_to_id[ext_concept.name] = cid
        for alias in ext_concept.aliases or []:
            name_to_id.setdefault(alias, cid)

    updated = 0
    for ext_concept, cid in zip(ext_concepts, concept_ids):
        if not ext_concept.prerequisites:
            continue

        # Resolve names to ids; drop unknowns, self-refs, and duplicates.
        candidates: list[UUID] = []
        seen: set[str] = set()
        for prereq_name in ext_concept.prerequisites:
            pid = name_to_id.get(prereq_name)
            if pid is None or pid == cid:
                continue
            if str(pid) in seen:
                continue
            candidates.append(pid)
            seen.add(str(pid))

        if not candidates:
            continue

        # Load existing prereqs to union-merge and to run the 2-cycle check.
        existing_row = await db.execute(
            select(Concept.prerequisites).where(Concept.id == cid)
        )
        existing = existing_row.scalar_one_or_none() or []
        existing_strs = {str(p) for p in existing}

        merged = list(existing)
        added_this_pass = False
        for pid in candidates:
            if str(pid) in existing_strs:
                continue
            # 2-cycle check: refuse pid as prereq of cid if cid is already
            # listed as a prereq of pid.
            rev_row = await db.execute(
                select(Concept.prerequisites).where(Concept.id == pid)
            )
            rev_prereqs = rev_row.scalar_one_or_none() or []
            if any(str(p) == str(cid) for p in rev_prereqs):
                continue
            merged.append(pid)
            existing_strs.add(str(pid))
            added_this_pass = True

        if added_this_pass:
            await db.execute(
                update(Concept)
                .where(Concept.id == cid)
                .values(prerequisites=merged)
            )
            updated += 1

    if updated:
        await db.flush()
        logger.info("Resolved prerequisites for %s concepts", updated)

    return updated
