"""Course generation service.

Owns all teaching-asset generation: lessons, labs, and the concept graph.
``ingest_source`` only produces the content fingerprint
(chunks + concepts + embeddings + analysis); the per-page LLM work that
turns that fingerprint into a learnable course lives here.

Lessons are written into ``Section.content``, labs into the ``Lab`` table.
The legacy ``source.metadata_["lesson_by_page"]`` etc. are still read as a
fallback when a course is assembled from a pre-Tier-2 source.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.models.lesson import CodeSnippet, LessonSourceChunk
from app.prompt_template import load_prompt
from app.services.lab_generator import LabGenerator
from app.services.lesson_generator import LessonGenerationError, LessonGenerator
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.services.research_enrichment import (
    FETCHED_REFERENCES_KEY,
    ResearchEnrichmentService,
    cards_from_metadata,
)

logger = logging.getLogger(__name__)

_DESCRIPTION_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "course_description.md")


_LOCAL_BASE_URL_HINTS = ("localhost", "127.0.0.1", "host.docker.internal", "ollama")


def _fetched_cards_for(sources: list[Source]) -> list:
    """Collect live-fetched reference cards cached on these sources at ingestion,
    so the enrichment pool includes real arXiv references (verified URLs)."""
    cards: list = []
    for source in sources:
        cards += cards_from_metadata((source.metadata_ or {}).get(FETCHED_REFERENCES_KEY))
    return cards


def _provider_is_local(provider) -> bool:
    """Heuristic — true when the provider points at a single-GPU local
    server. Used to clamp fanout concurrency to 1 there (PRD §11 phase B
    note: local serial, cloud parallel)."""
    base_url = getattr(provider, "_base_url", None)
    if not base_url:
        return False
    base_url = str(base_url).lower()
    return any(hint in base_url for hint in _LOCAL_BASE_URL_HINTS)


async def ensure_section_buckets(
    db: AsyncSession,
    source: Source,
    chunks: list[ContentChunkModel],
    model_router: ModelRouter,
) -> dict | None:
    """Run the zero-LLM SectionPlanner floor over ``chunks`` when they don't
    carry bucket assignments yet.

    Section planning lives at course-generation time (it's a course-level
    decision; ingestion only produces the content fingerprint). This floor
    guarantees assembly never sees bucket-less chunks — which would degrade
    to one-section-per-chunk — and doubles as the agentic outline's warm
    start and failure fallback.

    No-ops (returns ``None``) when there are no chunks, the source is
    page-structured (page assembly path), or buckets already exist (a prior
    generation or legacy ingestion-time planning). Mutates chunk metadata,
    writes ``section_planner_stats`` on the source, and flushes; the caller
    commits. ``chunks`` must be in source order (``_chunk_order_key``).
    """
    from types import SimpleNamespace

    from app.services.llm.token_budget import lesson_input_token_budget
    from app.services.section_planner import (
        SECTION_BUCKET_KEY,
        SECTION_BUCKET_TOPIC_KEY,
        SectionPlanner,
        has_section_buckets,
    )

    if not chunks:
        return None
    metas = [c.metadata_ or {} for c in chunks]
    if any(m.get("page_index") is not None for m in metas):
        return None
    if has_section_buckets(metas):
        return None

    raw = [
        SimpleNamespace(raw_text=c.text or "", metadata=m)
        for c, m in zip(chunks, metas)
    ]
    analyses = [
        SimpleNamespace(topic=m.get("topic") or "", summary=m.get("summary") or "")
        for m in metas
    ]
    embeddings = [
        list(c.embedding) if c.embedding is not None else [] for c in chunks
    ]

    try:
        provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
        cap: int | None = lesson_input_token_budget(provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ensure_section_buckets: no lesson provider for budget calc (%s); "
            "planner uses its conservative default cap",
            exc,
        )
        cap = None

    plan = await SectionPlanner().plan(
        chunks=raw,
        analyses=analyses,
        embeddings=embeddings,
        title=source.title or "Untitled",
        lesson_input_token_cap=cap,
    )
    # Reassign (not mutate) the JSONB dicts so SQLAlchemy change detection
    # marks the rows dirty.
    for chunk, bucket in zip(chunks, plan.assignments):
        merged = {**(chunk.metadata_ or {})}
        merged[SECTION_BUCKET_KEY] = bucket.bucket_id
        merged[SECTION_BUCKET_TOPIC_KEY] = bucket.bucket_topic
        chunk.metadata_ = merged
    source.metadata_ = {
        **(source.metadata_ or {}),
        "section_planner_stats": plan.stats,
    }
    await db.flush()
    logger.info(
        "Section floor: tier=%s buckets=%s chunks=%d for source %s",
        plan.stats.get("tier_used"),
        plan.stats.get("bucket_count"),
        len(chunks),
        source.id,
    )
    return plan.stats


class CourseGenerator:
    """Generates structured courses from analyzed sources."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def generate(
        self,
        db: AsyncSession,
        source_ids: list[UUID],
        target_language: str,
        title: str | None = None,
        user_id: UUID | None = None,
        skip_ready_check: bool = False,
        user_directive: str = "",
        cancel_check: "Callable[[], Awaitable[None]] | None" = None,
        section_progress_callback: "Callable[[UUID, dict], Awaitable[None]] | None" = None,
    ) -> Course:
        """Generate a course from one or more ingested sources.

        ``cancel_check``: optional async callable invoked at chunk-level
        break points. If it raises ``TaskCancelledError`` the generation
        bails out cooperatively. The Celery wrapper supplies a callback
        that polls the ``source_tasks.cancel_requested`` flag.
        """
        # 1. Validate sources
        sources: list[Source] = []
        for sid in source_ids:
            source = await db.get(Source, sid)
            if not source:
                raise ValueError(f"Source {sid} not found")
            if not skip_ready_check and source.status != "ready":
                raise ValueError(f"Source {sid} is not ready (status={source.status})")
            sources.append(source)

        # 2. Determine course title
        if not title:
            if len(sources) == 1:
                title = sources[0].title or "Untitled Course"
            else:
                title = f"Course from {len(sources)} sources"

        # 3. Load content chunks for these sources
        chunks_by_source: dict[UUID, list[ContentChunkModel]] = {}
        all_chunks: list[ContentChunkModel] = []
        for source in sources:
            result = await db.execute(
                select(ContentChunkModel)
                .where(ContentChunkModel.source_id == source.id)
                .order_by(ContentChunkModel.created_at)
            )
            rows = sorted(result.scalars().all(), key=self._chunk_order_key)
            chunks_by_source[source.id] = rows
            all_chunks.extend(rows)

        # 3.5 Section-bucket floor: planning happens at generation time, so
        # make sure no source reaches assembly bucket-less (that path degrades
        # to one-section-per-chunk). No-op for page-structured or already-
        # planned sources; a failure here must not abort generation.
        for source in sources:
            try:
                await ensure_section_buckets(
                    db, source, chunks_by_source[source.id], self._router
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Section floor failed for source %s; assembly may fall "
                    "back to per-chunk sections: %s",
                    source.id,
                    exc,
                )

        # Release the read transaction before LLM calls. Generation can sit
        # idle for minutes on local models; holding AccessShare/RowExclusive
        # locks across that wait blocks test cleanup, DDL, and maintenance.
        await db.commit()

        # 4. Generate teaching assets per source (lesson + lab + graph per page)
        provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
        lesson_gen = LessonGenerator(provider)
        lab_gen = LabGenerator(provider)
        research_enrichment = ResearchEnrichmentService(
            extra_cards=_fetched_cards_for(sources)
        )
        settings = get_settings()
        # Auto-tune chunk-level concurrency: local providers (ollama,
        # localhost-pointed) serialize anyway, so fanning out N parallel
        # calls just queues them server-side AND eats N retry budgets if
        # one stalls. Cloud providers benefit from the parallelism.
        configured = getattr(settings, "llm_max_concurrency", 4)
        sem = asyncio.Semaphore(
            1 if _provider_is_local(provider) else configured
        )

        per_source_assets: dict[UUID, _SourceAssets] = {}
        for source in sources:
            if cancel_check is not None:
                await cancel_check()
            assets = await self._generate_assets_for_source(
                source=source,
                chunks=chunks_by_source[source.id],
                lesson_gen=lesson_gen,
                lab_gen=lab_gen,
                research_enrichment=research_enrichment,
                sem=sem,
                target_language=target_language,
                user_directive=user_directive,
                cancel_check=cancel_check,
                section_progress_callback=section_progress_callback,
            )
            per_source_assets[source.id] = assets

        # 5. Generate course description via LLM before opening the write
        # transaction for the course rows.
        description = await self._generate_description(
            course_title=title,
            section_count=len(all_chunks),
            sources=sources,
            target_language=target_language,
        )

        # 6. Create Course
        course = Course(title=title, description=description, created_by=user_id)
        db.add(course)
        await db.flush()

        # 7. Link sources
        for source in sources:
            db.add(CourseSource(course_id=course.id, source_id=source.id))

        # 8. Create Sections (one per (source, page) group)
        await self._build_sections(
            db=db,
            course=course,
            sources=sources,
            chunks_by_source=chunks_by_source,
            per_source_assets=per_source_assets,
        )

        await db.flush()
        logger.info(
            "Generated course '%s' (%d sources, %d chunks)",
            title,
            len(sources),
            len(all_chunks),
        )
        return course

    async def _generate_assets_for_source(
        self,
        *,
        source: Source,
        chunks: list[ContentChunkModel],
        lesson_gen: LessonGenerator,
        lab_gen: LabGenerator,
        research_enrichment: ResearchEnrichmentService,
        sem: asyncio.Semaphore,
        target_language: str,
        user_directive: str,
        cancel_check: Callable[[], Awaitable[None]] | None = None,
        section_progress_callback: Callable[[UUID, dict], Awaitable[None]] | None = None,
    ) -> "_SourceAssets":
        """Plan + generate lessons/labs/graphs for one source, in parallel per page."""
        smeta = source.metadata_ or {}

        # Legacy data path: pre-Tier-2 sources still carry lesson/lab in metadata.
        # Use them as-is to avoid re-paying LLM cost.
        if smeta.get("lesson_by_page"):
            return _SourceAssets.from_legacy_metadata(smeta)

        # Group chunks by page_index
        page_groups: dict[int, list[ContentChunkModel]] = defaultdict(list)
        for chunk in chunks:
            cmeta = chunk.metadata_ or {}
            page_idx = cmeta.get("page_index", 0)
            page_groups[page_idx].append(chunk)

        asset_plan = smeta.get("asset_plan") or {"lab_mode": "none"}
        lab_mode = asset_plan.get("lab_mode", "none")

        # Videos (and other un-paginated sources) all collapse into page 0.
        # Generating a single lesson for the whole transcript and reusing it
        # for every chunk-derived section produces N identical sections — fix
        # by switching to bucket mode (preferred, when SectionPlanner has
        # written metadata) or per-chunk mode (legacy fallback) when
        # un-paginated.
        has_real_pages = any(
            (c.metadata_ or {}).get("page_index") is not None for c in chunks
        )
        # Bucket mode requires (a) no page index and (b) at least one chunk
        # carrying a SectionPlanner assignment. Mixed-state sources where
        # some chunks have buckets and others don't still flow through bucket
        # mode — missing chunks fall into bucket 0 and merge with whatever
        # else lands there.
        bucket_ids_present: set[int] = set()
        if not has_real_pages:
            for c in chunks:
                bid = (c.metadata_ or {}).get("section_bucket")
                if bid is not None:
                    try:
                        bucket_ids_present.add(int(bid))
                    except (TypeError, ValueError):
                        continue
        per_bucket_mode = (
            not has_real_pages and len(chunks) > 1 and len(bucket_ids_present) > 0
        )
        per_chunk_mode = (
            not has_real_pages and len(chunks) > 1 and not per_bucket_mode
        )

        # Group chunks by bucket once so both lesson generation and section
        # build use the same ordering. Bucket id falls back to 0 for chunks
        # missing the metadata key entirely.
        bucket_groups: dict[int, list[ContentChunkModel]] = defaultdict(list)
        if per_bucket_mode:
            for c in chunks:
                bid_raw = (c.metadata_ or {}).get("section_bucket", 0)
                try:
                    bid = int(bid_raw)
                except (TypeError, ValueError):
                    bid = 0
                bucket_groups[bid].append(c)

        section_progress_items: list[dict] = []
        section_progress_by_key: dict[str, dict] = {}
        section_progress_mode = "section"
        section_progress_lock = asyncio.Lock()

        def _append_section_progress_item(
            key: str,
            *,
            order_index: int,
            title: str,
        ) -> None:
            item = {
                "key": key,
                "order_index": order_index,
                "title": title,
                "status": "pending",
                "error": None,
            }
            section_progress_items.append(item)
            section_progress_by_key[key] = item

        async def _emit_section_progress() -> None:
            if section_progress_callback is None or not section_progress_items:
                return
            completed = sum(
                1
                for item in section_progress_items
                if item.get("status") in {"success", "failure"}
            )
            failed = sum(
                1 for item in section_progress_items if item.get("status") == "failure"
            )
            active = next(
                (
                    item["key"]
                    for item in section_progress_items
                    if item.get("status") == "running"
                ),
                None,
            )
            payload = {
                "mode": section_progress_mode,
                "total": len(section_progress_items),
                "completed": completed,
                "failed": failed,
                "active": active,
                "items": [dict(item) for item in section_progress_items],
            }
            try:
                await section_progress_callback(source.id, payload)
            except Exception:
                logger.warning(
                    "Failed to update section progress for source %s",
                    source.id,
                    exc_info=True,
                )

        async def _set_section_progress(
            key: str,
            status: str,
            error: str | None = None,
        ) -> None:
            async with section_progress_lock:
                item = section_progress_by_key.get(key)
                if not item:
                    return
                item["status"] = status
                item["error"] = error
                await _emit_section_progress()

        lesson_by_page: dict[int, dict] = {}
        lesson_by_chunk_id: dict[UUID, dict] = {}
        lesson_by_bucket_id: dict[int, dict] = {}
        error_by_page: dict[int, str] = {}
        error_by_chunk_id: dict[UUID, str] = {}
        error_by_bucket_id: dict[int, str] = {}

        if per_bucket_mode:
            section_progress_mode = "bucket"
            sorted_buckets = sorted(bucket_groups.keys())
            for order_index, bucket_id in enumerate(sorted_buckets):
                bucket_chunks = sorted(
                    bucket_groups[bucket_id], key=self._chunk_order_key
                )
                first_meta = bucket_chunks[0].metadata_ or {}
                bucket_title = (
                    first_meta.get("section_bucket_topic")
                    or first_meta.get("topic")
                    or source.title
                    or f"Section {order_index + 1}"
                )
                _append_section_progress_item(
                    f"bucket:{bucket_id}",
                    order_index=order_index,
                    title=str(bucket_title),
                )
            await _emit_section_progress()
            bucket_titles = {
                bucket_id: str(
                    (
                        sorted(
                            bucket_groups[bucket_id],
                            key=self._chunk_order_key,
                        )[0].metadata_
                        or {}
                    ).get(
                        "section_bucket_topic"
                    )
                    or (
                        sorted(
                            bucket_groups[bucket_id],
                            key=self._chunk_order_key,
                        )[0].metadata_
                        or {}
                    ).get("topic")
                    or source.title
                    or f"Section {idx + 1}"
                )
                for idx, bucket_id in enumerate(sorted_buckets)
            }
            bucket_index = {bucket_id: idx for idx, bucket_id in enumerate(sorted_buckets)}

            async def _gen_one_bucket_lesson(
                bucket_id: int, bucket_chunks: list[ContentChunkModel]
            ):
                async with sem:
                    progress_key = f"bucket:{bucket_id}"
                    await _set_section_progress(progress_key, "running")
                    if cancel_check is not None:
                        await cancel_check()
                    first_meta = bucket_chunks[0].metadata_ or {}
                    # Bucket topic from SectionPlanner is the strongest signal;
                    # fall back to first chunk's analyzer topic, then source title.
                    bucket_title = (
                        first_meta.get("section_bucket_topic")
                        or first_meta.get("topic")
                        or source.title
                        or "Untitled"
                    )
                    neighbor_index = bucket_index[bucket_id]
                    previous_title = (
                        bucket_titles[sorted_buckets[neighbor_index - 1]]
                        if neighbor_index > 0
                        else None
                    )
                    next_title = (
                        bucket_titles[sorted_buckets[neighbor_index + 1]]
                        if neighbor_index < len(sorted_buckets) - 1
                        else None
                    )
                    # Compact "just finished" context from the PREVIOUS bucket's
                    # chunk metadata (title + key terms/concepts). Pre-generation
                    # data only — never the previous lesson's generated recap,
                    # which may not exist yet under asyncio.gather.
                    previous_section_context = (
                        self._previous_section_context(
                            previous_title,
                            sorted(
                                bucket_groups[sorted_buckets[neighbor_index - 1]],
                                key=self._chunk_order_key,
                            ),
                        )
                        if neighbor_index > 0
                        else None
                    )
                    try:
                        lesson = await lesson_gen.generate(
                            subtitle_chunks=[c.text for c in bucket_chunks],
                            video_title=bucket_title,
                            target_language=target_language,
                            user_directive=user_directive,
                            source_chunks=self._lesson_source_chunks(bucket_chunks),
                            research_cards=research_enrichment.enrich(
                                section_title=str(bucket_title),
                                chunks=bucket_chunks,
                            ),
                            previous_section_title=previous_title,
                            next_section_title=next_title,
                            previous_section_context=previous_section_context,
                        )
                        await _set_section_progress(progress_key, "success")
                        return bucket_id, lesson, None
                    except LessonGenerationError as e:
                        logger.warning(
                            "Lesson generation failed for bucket %s: %s", bucket_id, e
                        )
                        await _set_section_progress(progress_key, "failure", str(e)[:500])
                        return bucket_id, None, str(e)[:500]

            bucket_results = await asyncio.gather(
                *(
                    _gen_one_bucket_lesson(
                        b,
                        sorted(bucket_groups[b], key=self._chunk_order_key),
                    )
                    for b in sorted_buckets
                )
            )
            for bid, lsn, err in bucket_results:
                if lsn is not None:
                    lesson_by_bucket_id[bid] = lsn.model_dump()
                elif err is not None:
                    error_by_bucket_id[bid] = err
        elif per_chunk_mode:
            section_progress_mode = "chunk"
            for order_index, chunk in enumerate(chunks):
                cmeta = chunk.metadata_ or {}
                chunk_title = (
                    cmeta.get("topic")
                    or cmeta.get("page_title")
                    or source.title
                    or f"Section {order_index + 1}"
                )
                _append_section_progress_item(
                    f"chunk:{chunk.id}",
                    order_index=order_index,
                    title=str(chunk_title),
                )
            await _emit_section_progress()
            chunk_titles = []
            for order_index, chunk in enumerate(chunks):
                cmeta = chunk.metadata_ or {}
                chunk_titles.append(
                    str(
                        cmeta.get("topic")
                        or cmeta.get("page_title")
                        or source.title
                        or f"Section {order_index + 1}"
                    )
                )

            async def _gen_one_chunk_lesson(
                order_index: int, chunk: ContentChunkModel
            ):
                async with sem:
                    progress_key = f"chunk:{chunk.id}"
                    await _set_section_progress(progress_key, "running")
                    if cancel_check is not None:
                        await cancel_check()
                    cmeta = chunk.metadata_ or {}
                    chunk_title = (
                        cmeta.get("topic")
                        or cmeta.get("page_title")
                        or source.title
                        or "Untitled"
                    )
                    previous_section_context = (
                        self._previous_section_context(
                            chunk_titles[order_index - 1],
                            [chunks[order_index - 1]],
                        )
                        if order_index > 0
                        else None
                    )
                    try:
                        lesson = await lesson_gen.generate(
                            subtitle_chunks=[chunk.text],
                            video_title=chunk_title,
                            target_language=target_language,
                            user_directive=user_directive,
                            source_chunks=self._lesson_source_chunks([chunk]),
                            research_cards=research_enrichment.enrich(
                                section_title=str(chunk_title),
                                chunks=[chunk],
                            ),
                            previous_section_title=(
                                chunk_titles[order_index - 1]
                                if order_index > 0
                                else None
                            ),
                            next_section_title=(
                                chunk_titles[order_index + 1]
                                if order_index < len(chunk_titles) - 1
                                else None
                            ),
                            previous_section_context=previous_section_context,
                        )
                        await _set_section_progress(progress_key, "success")
                        return chunk.id, lesson, None
                    except LessonGenerationError as e:
                        logger.warning(
                            "Lesson generation failed for chunk %s: %s", chunk.id, e
                        )
                        await _set_section_progress(progress_key, "failure", str(e)[:500])
                        return chunk.id, None, str(e)[:500]

            chunk_results = await asyncio.gather(
                *(_gen_one_chunk_lesson(i, c) for i, c in enumerate(chunks))
            )
            for cid, lsn, err in chunk_results:
                if lsn is not None:
                    lesson_by_chunk_id[cid] = lsn.model_dump()
                elif err is not None:
                    error_by_chunk_id[cid] = err
        else:
            section_progress_mode = "page"
            sorted_pages = sorted(page_groups.keys())
            page_title_by_index: dict[int, str] = {}
            for order_index, page_idx in enumerate(sorted_pages):
                page_chunks = sorted(page_groups[page_idx], key=self._chunk_order_key)
                page_groups[page_idx] = page_chunks
                first_meta = page_chunks[0].metadata_ or {}
                page_title = first_meta.get("page_title") or source.title or f"Section {order_index + 1}"
                page_title_by_index[page_idx] = str(page_title)
                _append_section_progress_item(
                    f"page:{page_idx}",
                    order_index=order_index,
                    title=str(page_title),
                )
            await _emit_section_progress()
            page_index = {page_idx: idx for idx, page_idx in enumerate(sorted_pages)}

            # Run lesson generation in parallel across pages
            async def _gen_one_lesson(page_idx: int, page_chunks: list[ContentChunkModel]):
                async with sem:
                    progress_key = f"page:{page_idx}"
                    await _set_section_progress(progress_key, "running")
                    if cancel_check is not None:
                        await cancel_check()
                    first_meta = page_chunks[0].metadata_ or {}
                    page_title = (
                        first_meta.get("page_title") or source.title or "Untitled"
                    )
                    neighbor_index = page_index[page_idx]
                    previous_title = (
                        page_title_by_index[sorted_pages[neighbor_index - 1]]
                        if neighbor_index > 0
                        else None
                    )
                    next_title = (
                        page_title_by_index[sorted_pages[neighbor_index + 1]]
                        if neighbor_index < len(sorted_pages) - 1
                        else None
                    )
                    previous_section_context = (
                        self._previous_section_context(
                            previous_title,
                            page_groups[sorted_pages[neighbor_index - 1]],
                        )
                        if neighbor_index > 0
                        else None
                    )
                    try:
                        lesson = await lesson_gen.generate(
                            subtitle_chunks=[c.text for c in page_chunks],
                            video_title=page_title,
                            target_language=target_language,
                            user_directive=user_directive,
                            source_chunks=self._lesson_source_chunks(page_chunks),
                            research_cards=research_enrichment.enrich(
                                section_title=str(page_title),
                                chunks=page_chunks,
                            ),
                            previous_section_title=previous_title,
                            next_section_title=next_title,
                            previous_section_context=previous_section_context,
                        )
                        await _set_section_progress(progress_key, "success")
                        return page_idx, lesson, None
                    except LessonGenerationError as e:
                        logger.warning(
                            "Lesson generation failed for page %s: %s", page_idx, e
                        )
                        await _set_section_progress(progress_key, "failure", str(e)[:500])
                        return page_idx, None, str(e)[:500]

            lesson_results = await asyncio.gather(
                *(_gen_one_lesson(p, page_groups[p]) for p in sorted_pages)
            )
            for p, lsn, err in lesson_results:
                if lsn is not None:
                    lesson_by_page[p] = lsn.model_dump()
                elif err is not None:
                    error_by_page[p] = err

        # Build graph cards from lesson concept_relation blocks
        suggested_prereqs = smeta.get("suggested_prerequisites", [])

        def _build_graph_card(lesson_dict: dict, anchor: int | str) -> dict:
            key_concepts: list[str] = []
            for block in lesson_dict.get("blocks", []):
                if block.get("type") == "concept_relation":
                    for c in block.get("concepts", []):
                        label = c.get("label") if isinstance(c, dict) else None
                        if label:
                            key_concepts.append(label)
            deduped = list(dict.fromkeys(key_concepts))
            return {
                "current": deduped[:2],
                "prerequisites": suggested_prereqs[:3],
                "unlocks": deduped[2:5],
                "section_anchor": anchor,
            }

        graph_by_page: dict[int, dict] = {}
        for page_idx, lesson_dict in lesson_by_page.items():
            graph_by_page[page_idx] = _build_graph_card(lesson_dict, page_idx)

        graph_by_bucket_id: dict[int, dict] = {}
        for bucket_id, lesson_dict in lesson_by_bucket_id.items():
            graph_by_bucket_id[bucket_id] = _build_graph_card(lesson_dict, bucket_id)

        # Run lab generation in parallel where lab_mode == "inline".
        # Only meaningful when per-page lessons exist; per-chunk and per-bucket
        # paths attach a single course-level lab via _build_sections instead.
        labs_by_page: dict[int, dict | None] = {}
        if lab_mode == "inline" and lesson_by_page:
            async def _gen_one_lab(page_idx: int, lesson_dict: dict):
                async with sem:
                    snippets = [
                        CodeSnippet(
                            language=block.get("language") or "python",
                            code=block.get("code") or "",
                            context=block.get("body") or "",
                        )
                        for block in lesson_dict.get("blocks", [])
                        if block.get("type") == "code_example" and block.get("code")
                    ]
                    if not snippets:
                        return page_idx, None
                    lang_counts: dict[str, int] = {}
                    for s in snippets:
                        lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
                    language = max(lang_counts, key=lang_counts.__getitem__)
                    lab = await lab_gen.generate(
                        code_snippets=snippets,
                        lesson_context=lesson_dict.get("summary", ""),
                        language=language,
                        target_language=target_language,
                        user_directive=user_directive,
                    )
                    return page_idx, lab

            lab_results = await asyncio.gather(
                *(_gen_one_lab(p, lesson_by_page[p]) for p in sorted_pages)
            )
            for page_idx, lab in lab_results:
                if lab is not None:
                    labs_by_page[page_idx] = lab

        return _SourceAssets(
            lesson_by_page=lesson_by_page,
            graph_by_page=graph_by_page,
            labs_by_page=labs_by_page,
            lab_mode=lab_mode,
            lesson_by_chunk_id=lesson_by_chunk_id,
            error_by_page=error_by_page,
            error_by_chunk_id=error_by_chunk_id,
            lesson_by_bucket_id=lesson_by_bucket_id,
            graph_by_bucket_id=graph_by_bucket_id,
            labs_by_bucket_id={},
            error_by_bucket_id=error_by_bucket_id,
        )

    async def _build_sections(
        self,
        *,
        db: AsyncSession,
        course: Course,
        sources: list[Source],
        chunks_by_source: dict[UUID, list[ContentChunkModel]],
        per_source_assets: dict[UUID, "_SourceAssets"],
    ) -> None:
        """Create Section + Lab rows from generated assets."""
        from app.db.models.lab import Lab

        all_chunks = [c for cs in chunks_by_source.values() for c in cs]
        research_enrichment = ResearchEnrichmentService(
            extra_cards=_fetched_cards_for(sources)
        )
        has_page_index = any(
            (c.metadata_ or {}).get("page_index") is not None for c in all_chunks
        )
        has_section_buckets = (not has_page_index) and any(
            (c.metadata_ or {}).get("section_bucket") is not None for c in all_chunks
        )

        if has_page_index:
            page_groups: dict[tuple[UUID, int], list[ContentChunkModel]] = defaultdict(list)
            for chunk in all_chunks:
                page_idx = (chunk.metadata_ or {}).get("page_index", 0)
                page_groups[(chunk.source_id, page_idx)].append(chunk)

            section_order = 0
            for (source_id, page_idx), group_chunks in sorted(
                page_groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])
            ):
                group_chunks = sorted(group_chunks, key=self._chunk_order_key)
                first_meta = group_chunks[0].metadata_ or {}
                assets = per_source_assets.get(source_id) or _SourceAssets.empty()
                lesson = assets.lesson_for(page_idx)
                graph = assets.graph_for(page_idx)
                lab_data = assets.lab_for(page_idx)
                lesson_error = None if lesson else assets.error_for(page_idx)

                section_title = (
                    (lesson or {}).get("title")
                    or first_meta.get("page_title")
                    or first_meta.get("topic")
                    or f"Section {section_order + 1}"
                )

                section_content = {
                    "summary": (lesson or {}).get("summary") or first_meta.get("summary", ""),
                    "key_terms": first_meta.get("key_terms", []),
                    "has_code": any((c.metadata_ or {}).get("has_code") for c in group_chunks),
                    "lab_mode": assets.lab_mode,
                    "graph_card": graph,
                    "research_cards": [
                        card.model_dump(exclude_none=True)
                        for card in research_enrichment.enrich(
                            section_title=str(section_title),
                            chunks=group_chunks,
                        )
                    ],
                }
                if lesson:
                    section_content["lesson"] = lesson

                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=section_order,
                    source_id=source_id,
                    source_start=self._format_source_ref(first_meta, "start"),
                    source_end=self._format_source_ref(
                        (group_chunks[-1].metadata_ or {}), "end"
                    ),
                    content=section_content,
                    difficulty=first_meta.get("difficulty", 1),
                    lesson_generation_error=lesson_error,
                )
                db.add(section)
                await db.flush()
                for chunk in group_chunks:
                    chunk.section_id = section.id

                if assets.lab_mode == "inline" and lab_data:
                    await self._create_lab(db, section.id, lab_data)

                section_order += 1
        elif has_section_buckets:
            # Bucket grouping: SectionPlanner has tagged each chunk with a
            # section_bucket id. Consecutive chunks sharing a bucket merge
            # into one section. Source order is preserved by sorting on the
            # bucket's first chunk's created_at (stable across regenerations
            # because chunks are inserted in extraction order in STEP 5).
            bucket_groups: dict[tuple[UUID, int], list[ContentChunkModel]] = defaultdict(list)
            for chunk in all_chunks:
                bid_raw = (chunk.metadata_ or {}).get("section_bucket", 0)
                try:
                    bid = int(bid_raw)
                except (TypeError, ValueError):
                    bid = 0
                bucket_groups[(chunk.source_id, bid)].append(chunk)

            # Sort bucket groups: primary by source id (stable across runs),
            # secondary by min(created_at) within bucket so source-order
            # within a source is preserved even if bucket ids are not
            # monotonic across the chunk sequence (defensive).
            def _bucket_sort_key(item):
                (source_id, bid), group = item
                first_chunk = min(group, key=self._chunk_order_key)
                return (str(source_id), self._chunk_order_key(first_chunk), bid)

            section_order = 0
            attached_lab_sources: set[UUID] = set()
            for (source_id, bid), group_chunks in sorted(
                bucket_groups.items(), key=_bucket_sort_key
            ):
                group_chunks = sorted(group_chunks, key=self._chunk_order_key)
                first_meta = group_chunks[0].metadata_ or {}
                last_meta = group_chunks[-1].metadata_ or {}
                assets = per_source_assets.get(source_id) or _SourceAssets.empty()
                lesson = assets.lesson_for_bucket(bid)
                graph = assets.graph_for_bucket(bid)
                lesson_error = None if lesson else assets.error_for_bucket(bid)

                bucket_topic = first_meta.get("section_bucket_topic")
                section_title = (
                    (lesson or {}).get("title")
                    or bucket_topic
                    or first_meta.get("topic")
                    or f"Section {section_order + 1}"
                )

                section_content = {
                    "summary": (lesson or {}).get("summary") or first_meta.get("summary", ""),
                    "key_terms": first_meta.get("key_terms", []),
                    "has_code": any((c.metadata_ or {}).get("has_code") for c in group_chunks),
                    "lab_mode": assets.lab_mode,
                    "graph_card": graph,
                    "research_cards": [
                        card.model_dump(exclude_none=True)
                        for card in research_enrichment.enrich(
                            section_title=str(section_title),
                            chunks=group_chunks,
                        )
                    ],
                }
                if lesson:
                    section_content["lesson"] = lesson

                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=section_order,
                    source_id=source_id,
                    source_start=self._format_source_ref(first_meta, "start"),
                    source_end=self._format_source_ref(last_meta, "end"),
                    content=section_content,
                    difficulty=first_meta.get("difficulty", 1),
                    lesson_generation_error=lesson_error,
                )
                db.add(section)
                await db.flush()
                for chunk in group_chunks:
                    chunk.section_id = section.id

                # One lab per source: attach to the first bucket section we
                # produce for that source. Matches the per_chunk_mode rule
                # below; videos/plain text don't get per-bucket inline labs.
                if (
                    assets.lab_mode == "inline"
                    and source_id not in attached_lab_sources
                ):
                    lab_data = assets.lab_for(0)
                    if lab_data:
                        await self._create_lab(db, section.id, lab_data)
                        attached_lab_sources.add(source_id)

                section_order += 1
        else:
            # No page grouping: one section per chunk. Prefer a per-chunk
            # lesson when available (videos, plain text) so each section has
            # distinct title/content instead of N copies of the shared lesson.
            for i, chunk in enumerate(all_chunks):
                metadata = chunk.metadata_ or {}
                source_id = chunk.source_id
                assets = per_source_assets.get(source_id) or _SourceAssets.empty()
                lesson = assets.lesson_for_chunk(chunk.id) or assets.lesson_for(0)
                graph = assets.graph_for(0)
                lesson_error = (
                    None if lesson
                    else assets.error_for_chunk(chunk.id) or assets.error_for(0)
                )

                section_title = (
                    (lesson or {}).get("title")
                    or metadata.get("topic")
                    or f"Section {i + 1}"
                )
                section_content = {
                    "summary": (lesson or {}).get("summary") or metadata.get("summary", ""),
                    "key_terms": metadata.get("key_terms", []),
                    "has_code": metadata.get("has_code", False),
                    "lab_mode": assets.lab_mode,
                    "graph_card": graph,
                    "research_cards": [
                        card.model_dump(exclude_none=True)
                        for card in research_enrichment.enrich(
                            section_title=str(section_title),
                            chunks=[chunk],
                        )
                    ],
                }
                if lesson:
                    section_content["lesson"] = lesson

                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=i,
                    source_id=source_id,
                    source_start=self._format_source_ref(metadata, "start"),
                    source_end=self._format_source_ref(metadata, "end"),
                    content=section_content,
                    difficulty=metadata.get("difficulty", 1),
                    lesson_generation_error=lesson_error,
                )
                db.add(section)
                await db.flush()
                chunk.section_id = section.id

            # One lab per source if available, attached to the first section.
            attached_to: set[UUID] = set()
            for chunk in all_chunks:
                src_id = chunk.source_id
                if src_id in attached_to:
                    continue
                assets = per_source_assets.get(src_id) or _SourceAssets.empty()
                lab_data = assets.lab_for(0)
                if assets.lab_mode == "inline" and lab_data and chunk.section_id:
                    await self._create_lab(db, chunk.section_id, lab_data)
                    attached_to.add(src_id)

        await db.flush()

    @staticmethod
    async def _create_lab(db: AsyncSession, section_id: UUID, lab_data: dict) -> None:
        from app.db.models.lab import Lab

        lab = Lab(
            section_id=section_id,
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
        await db.flush()
        logger.info("Created lab '%s' for section %s", lab.title, section_id)

    @staticmethod
    def _previous_section_context(
        previous_title: str | None,
        previous_chunks: list[ContentChunkModel],
    ) -> str | None:
        """Build a compact "what the learner just finished" line.

        Uses ONLY pre-generation data — the previous section's title plus the
        top key terms/concepts pulled from that section's chunk metadata
        (``key_terms`` / ``concepts`` / ``topic``). This is intentionally cheap
        (no LLM, no generated recap) so it can be assembled upfront and passed
        into a lesson that still generates in parallel with its neighbors.

        Returns ``None`` when there is no usable signal (e.g. the first
        section) so callers leave continuity off and reproduce prior behavior.
        """
        terms: list[str] = []
        for chunk in previous_chunks:
            metadata = chunk.metadata_ or {}
            for key in ("key_terms", "concepts"):
                value = metadata.get(key)
                if isinstance(value, list):
                    terms.extend(str(v) for v in value if v)
            topic = metadata.get("topic")
            if isinstance(topic, str) and topic.strip():
                terms.append(topic.strip())

        # Dedup case-insensitively, preserve first-seen order, cap to ~5 items
        # so the prompt line stays short.
        seen: set[str] = set()
        deduped: list[str] = []
        for term in terms:
            cleaned = term.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(cleaned)
            if len(deduped) >= 5:
                break

        title = (previous_title or "").strip()
        if not title and not deduped:
            return None
        if title and deduped:
            return f"{title} — {', '.join(deduped)}"
        if title:
            return title
        return ", ".join(deduped)

    @staticmethod
    def _lesson_source_chunks(
        chunks: list[ContentChunkModel],
    ) -> list[LessonSourceChunk]:
        items: list[LessonSourceChunk] = []
        for chunk in sorted(chunks, key=CourseGenerator._chunk_order_key):
            metadata = chunk.metadata_ or {}
            concepts = metadata.get("concepts", [])
            key_terms = metadata.get("key_terms", [])
            items.append(
                LessonSourceChunk(
                    text=chunk.text,
                    topic=metadata.get("topic") if isinstance(metadata.get("topic"), str) else None,
                    summary=metadata.get("summary") if isinstance(metadata.get("summary"), str) else None,
                    start_sec=CourseGenerator._coerce_float(metadata.get("start_time")),
                    end_sec=CourseGenerator._coerce_float(metadata.get("end_time")),
                    concepts=[str(c) for c in concepts] if isinstance(concepts, list) else [],
                    key_terms=[str(k) for k in key_terms] if isinstance(key_terms, list) else [],
                )
            )
        return items

    @staticmethod
    def _chunk_order_key(chunk: ContentChunkModel) -> tuple:
        metadata = chunk.metadata_ or {}
        page_idx = CourseGenerator._coerce_float(metadata.get("page_index"))
        start = CourseGenerator._coerce_float(metadata.get("start_time"))
        page_start = CourseGenerator._coerce_float(metadata.get("page_start"))
        created_at = getattr(chunk, "created_at", None)
        created_key = created_at.isoformat() if created_at is not None else ""
        if start is not None:
            return (0, page_idx if page_idx is not None else 0, start, created_key, str(chunk.id))
        if page_start is not None:
            return (1, page_start, created_key, str(chunk.id))
        if page_idx is not None:
            return (2, page_idx, created_key, str(chunk.id))
        return (3, created_key, str(chunk.id))

    @staticmethod
    def _format_source_ref(metadata: dict, ref_type: str) -> str | None:
        if "start_time" in metadata and ref_type == "start":
            start = CourseGenerator._coerce_float(metadata.get("start_time"))
            return f"{start:.0f}s" if start is not None else None
        if "end_time" in metadata and ref_type == "end":
            end = CourseGenerator._coerce_float(metadata.get("end_time"))
            return f"{end:.0f}s" if end is not None else None
        if "page_start" in metadata and ref_type == "start":
            return f"p{metadata['page_start']}"
        if "page_end" in metadata and ref_type == "end":
            return f"p{metadata['page_end']}"
        return None

    @staticmethod
    def _coerce_float(value: object) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    async def _generate_description(
        self,
        course_title: str,
        section_count: int,
        sources: list[Source],
        target_language: str,
    ) -> str:
        try:
            provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
            source_info = ", ".join(s.title or s.url or "unknown" for s in sources)
            messages = [
                UnifiedMessage(
                    role="user",
                    content=_DESCRIPTION_PROMPT.render(
                        course_title=course_title,
                        section_count=section_count,
                        source_info=source_info,
                        target_language=target_language,
                    ),
                ),
            ]
            response = await provider.chat(messages, max_tokens=256, temperature=0.5)
            return "".join(b.text or "" for b in response.content if b.type == "text").strip()
        except Exception:
            logger.warning("Failed to generate course description, using fallback")
            return f"A course based on {len(sources)} source(s) with {section_count} sections."


class _SourceAssets:
    """Aggregated lesson/lab/graph dicts keyed by page index or bucket id.

    Three keying schemes coexist so the generator can serve all three
    grouping modes without per-mode subclasses:
      * ``*_by_page`` — paginated sources (PDF, etc.)
      * ``*_by_bucket_id`` — sources with SectionPlanner output
      * ``*_by_chunk_id`` — legacy per-chunk fallback
    """

    def __init__(
        self,
        *,
        lesson_by_page: dict[int, dict],
        graph_by_page: dict[int, dict],
        labs_by_page: dict[int, dict | None],
        lab_mode: str,
        lesson_by_chunk_id: dict[UUID, dict] | None = None,
        error_by_page: dict[int, str] | None = None,
        error_by_chunk_id: dict[UUID, str] | None = None,
        lesson_by_bucket_id: dict[int, dict] | None = None,
        graph_by_bucket_id: dict[int, dict] | None = None,
        labs_by_bucket_id: dict[int, dict | None] | None = None,
        error_by_bucket_id: dict[int, str] | None = None,
    ) -> None:
        self.lesson_by_page = lesson_by_page
        self.graph_by_page = graph_by_page
        self.labs_by_page = labs_by_page
        self.lab_mode = lab_mode
        self.lesson_by_chunk_id = lesson_by_chunk_id or {}
        self.error_by_page = error_by_page or {}
        self.error_by_chunk_id = error_by_chunk_id or {}
        self.lesson_by_bucket_id = lesson_by_bucket_id or {}
        self.graph_by_bucket_id = graph_by_bucket_id or {}
        self.labs_by_bucket_id = labs_by_bucket_id or {}
        self.error_by_bucket_id = error_by_bucket_id or {}

    @classmethod
    def empty(cls) -> "_SourceAssets":
        return cls(
            lesson_by_page={},
            graph_by_page={},
            labs_by_page={},
            lab_mode="none",
            lesson_by_chunk_id={},
        )

    @classmethod
    def from_legacy_metadata(cls, smeta: dict) -> "_SourceAssets":
        """Build from pre-Tier-2 source.metadata_."""
        def _intkeys(d: dict | None) -> dict:
            if not d:
                return {}
            return {int(k) if str(k).isdigit() else k: v for k, v in d.items()}

        labs_by_page = _intkeys(smeta.get("labs_by_page"))
        asset_plan = smeta.get("asset_plan") or {}
        # Legacy sources sometimes have labs_by_page but no asset_plan; if the
        # legacy data carries any non-null lab dict, infer lab_mode=inline.
        legacy_inline = any(v for v in labs_by_page.values())
        lab_mode = asset_plan.get("lab_mode") or ("inline" if legacy_inline else "none")
        return cls(
            lesson_by_page=_intkeys(smeta.get("lesson_by_page")),
            graph_by_page=_intkeys(smeta.get("graph_by_page")),
            labs_by_page=labs_by_page,
            lab_mode=lab_mode,
        )

    def lesson_for(self, page_idx: int) -> dict | None:
        return self.lesson_by_page.get(page_idx) or self.lesson_by_page.get(str(page_idx))

    def lesson_for_chunk(self, chunk_id: UUID) -> dict | None:
        return self.lesson_by_chunk_id.get(chunk_id)

    def lesson_for_bucket(self, bucket_id: int) -> dict | None:
        return self.lesson_by_bucket_id.get(bucket_id) or self.lesson_by_bucket_id.get(
            str(bucket_id)
        )

    def graph_for(self, page_idx: int) -> dict | None:
        return self.graph_by_page.get(page_idx) or self.graph_by_page.get(str(page_idx))

    def graph_for_bucket(self, bucket_id: int) -> dict | None:
        return self.graph_by_bucket_id.get(bucket_id) or self.graph_by_bucket_id.get(
            str(bucket_id)
        )

    def lab_for(self, page_idx: int) -> dict | None:
        return self.labs_by_page.get(page_idx) or self.labs_by_page.get(str(page_idx))

    def lab_for_bucket(self, bucket_id: int) -> dict | None:
        return self.labs_by_bucket_id.get(bucket_id) or self.labs_by_bucket_id.get(
            str(bucket_id)
        )

    def error_for(self, page_idx: int) -> str | None:
        return self.error_by_page.get(page_idx) or self.error_by_page.get(str(page_idx))

    def error_for_chunk(self, chunk_id: UUID) -> str | None:
        return self.error_by_chunk_id.get(chunk_id)

    def error_for_bucket(self, bucket_id: int) -> str | None:
        return self.error_by_bucket_id.get(bucket_id) or self.error_by_bucket_id.get(
            str(bucket_id)
        )
