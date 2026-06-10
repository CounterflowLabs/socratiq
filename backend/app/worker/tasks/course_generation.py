"""Course generation Celery task — assembles courses from persisted source assets."""

import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.agentcore.events import (
    EventBus,
    RedisEventSink,
    TracerEventSink,
    run_error,
    run_finished,
    run_started,
)
from app.config import get_settings
from app.services.source_tasks import mark_source_task
from app.worker._compat import task_shim

logger = logging.getLogger(__name__)


async def generate_course(
    ctx: dict,
    ingest_result: dict,
    user_id: str | None = None,
    goal: str | None = None,
) -> dict:
    """Generate a course from an ingested source.

    Wraps the generation with an AG-UI run: a per-run Redis event stream
    (``RedisEventSink``) lets the web process re-stream live progress over SSE
    (replacing polling). ``run_id`` is the ARQ job id, which the frontend
    already holds as the course task id.

    Args:
        ctx: ARQ job context (carries shared ``resources`` and ``job_id``).
        ingest_result: Result dict from ingest_source/clone_source (has source_id).
        user_id: User UUID string for course ownership.
        goal: Legacy compatibility kwarg from older producers; ignored.
    """
    source_id = ingest_result["source_id"]
    run_id = ctx.get("job_id") or source_id
    redis = aioredis.from_url(get_settings().redis_url)
    bus = EventBus(
        thread_id=source_id,
        run_id=run_id,
        sinks=[RedisEventSink(redis, run_id), TracerEventSink()],
    )
    await bus.emit(run_started(thread_id=source_id, run_id=run_id))
    try:
        result = await _generate_course_async(
            task_shim(ctx), source_id, user_id, ctx["resources"], event_bus=bus
        )
    except Exception as exc:  # noqa: BLE001
        await bus.emit(run_error(message=str(exc)))
        await bus.aclose()
        await redis.aclose()
        raise
    await bus.emit(
        run_finished(thread_id=source_id, run_id=run_id, result=result)
    )
    await bus.aclose()
    await redis.aclose()
    return result


async def _generate_course_async(
    task, source_id: str, user_id: str | None, resources, event_bus=None
) -> dict:
    """Async implementation of course generation."""
    from sqlalchemy import select
    from app.db.models.course import Section
    from app.db.models.lab import Lab
    from app.db.models.source import Source
    from app.db.models.source_task import SourceTask
    from app.services.course_generator import CourseGenerator
    from app.services.source_tasks import (
        TaskCancelledError,
        is_cancel_requested,
    )

    sid = UUID(source_id)
    uid = UUID(user_id) if user_id else None

    async def _check_cancel():
        async with resources.session_factory() as poll_db:
            if await is_cancel_requested(
                poll_db, source_id=sid, task_type="course_generation"
            ):
                raise TaskCancelledError(
                    f"course_generation cancelled for source {source_id}"
                )

    from app.agentcore.events import state_snapshot

    async def _report_section_progress(_source_id: UUID, progress: dict) -> None:
        async with resources.session_factory() as progress_db:
            await mark_source_task(
                progress_db,
                source_id=_source_id,
                task_type="course_generation",
                status="running",
                stage="assembling_course",
                metadata_={"section_progress": progress},
            )
            await progress_db.commit()
        # AG-UI live progress: re-snapshot the full progress payload each
        # update (small + idempotent; the client replaces its state).
        if event_bus is not None:
            await event_bus.emit(state_snapshot(progress))

    try:
        async with resources.session_factory() as db:
            source = await db.get(Source, sid)
            if not source or source.status != "ready":
                raise ValueError(f"Source {source_id} not ready for course generation")

            # Idempotency: a redelivered task for a source whose course is
            # already generated should return the existing course_id.
            existing_task = (
                await db.execute(
                    select(SourceTask)
                    .where(
                        SourceTask.source_id == sid,
                        SourceTask.task_type == "course_generation",
                        SourceTask.status == "success",
                    )
                    .order_by(SourceTask.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_task and existing_task.metadata_.get("course_id"):
                existing_course_id = existing_task.metadata_["course_id"]
                logger.info(
                    "Skipping course generation for %s: already produced %s",
                    source_id,
                    existing_course_id,
                )
                # The current run's SourceTask row (preallocated by the
                # ingest finalizer) is still ``pending``. Mark it success so
                # /sources/{id}/progress doesn't show a perpetual "课程生成中"
                # for the loser of the concurrent-ingest race.
                await mark_source_task(
                    db,
                    source_id=sid,
                    task_type="course_generation",
                    status="success",
                    stage="ready",
                    metadata_={"course_id": existing_course_id},
                )
                await db.commit()
                return {
                    "source_id": source_id,
                    "course_id": existing_course_id,
                    "status": "ready",
                    "skipped": True,
                }

            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="running",
                stage="planning",
            )
            task.update_state(state="PROGRESS", meta={"stage": "planning"})

            from app.services.profile import load_profile

            # Tier 2: prefer the course owner's language over the uploader's,
            # so multiple users can derive courses in their preferred language
            # from the same source.
            target_language = "zh-CN"
            if uid is not None:
                owner_profile = await load_profile(db, uid)
                target_language = owner_profile.preferred_language
            elif source.created_by is not None:
                uploader_profile = await load_profile(db, source.created_by)
                target_language = uploader_profile.preferred_language

            # Section-bucket floor (planning happens at generation time, not
            # ingestion): run the zero-LLM SectionPlanner BEFORE the agentic
            # outline so (a) the outline gets a warm start and (b) its failure
            # path falls back to floor buckets instead of per-chunk
            # fragmentation. Committed immediately so a later agentic rollback
            # can't undo it.
            try:
                floor_stats = await _ensure_floor_buckets(db, source, sid, resources)
                if floor_stats:
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Section floor failed for source %s; relying on the "
                    "generator-side fallback: %s",
                    source_id,
                    exc,
                )
                await db.rollback()

            # Agentic outline (Phase 3): when enabled, re-plan the section
            # structure with the critic-gated video→course graph and write the
            # result onto chunk metadata BEFORE assembly. CourseGenerator then
            # consumes the new buckets unchanged. Committed here so the
            # generator's own re-query (it reloads chunks) sees the new buckets.
            if get_settings().agentic_video_pipeline:
                try:
                    n_sections = await _maybe_run_agentic_outline(
                        db, source, sid, resources, event_bus, target_language
                    )
                    if n_sections:
                        await db.commit()
                except Exception as exc:  # noqa: BLE001
                    # Never let outline planning abort generation — fall back
                    # to the floor buckets committed above. The course still
                    # generates; it just isn't re-planned.
                    logger.warning(
                        "Agentic outline failed for source %s; using floor "
                        "buckets: %s",
                        source_id,
                        exc,
                    )
                    await db.rollback()

            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="running",
                stage="assembling_course",
            )
            await db.commit()
            task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})

            generator = CourseGenerator(resources.model_router)
            course = await generator.generate(
                db=db,
                source_ids=[sid],
                title=source.title,
                user_id=uid,
                skip_ready_check=True,
                target_language=target_language,
                cancel_check=_check_cancel,
                section_progress_callback=_report_section_progress,
            )

            sections = (
                await db.execute(
                    select(Section).where(Section.course_id == course.id)
                )
            ).scalars().all()
            labs = (
                await db.execute(
                    select(Lab)
                    .join(Section, Lab.section_id == Section.id)
                    .where(Section.course_id == course.id)
                )
            ).scalars().all()

            # Agentic self-check (Phase 3/4): run the critic over the assembled
            # course and publish the verdict. Behind a flag so the default path
            # is unchanged; the verdict is advisory for now (re-plan/backtrack
            # requires the full graph decomposition).
            if get_settings().agentic_video_pipeline and event_bus is not None:
                await _run_course_critic(sections, event_bus, resources)

            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="success",
                stage="ready",
                metadata_={"course_id": str(course.id)},
            )
            await db.commit()

            logger.info(
                "Generated course '%s' with %s sections",
                course.title,
                len(sections),
            )
            return {
                "source_id": source_id,
                "course_id": str(course.id),
                "title": course.title,
                "sections_created": len(sections),
                "labs_created": len(labs),
                "status": "ready",
            }
    except TaskCancelledError as exc:
        logger.info("Course generation cancelled for source %s: %s", source_id, exc)
        async with resources.session_factory() as db:
            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="cancelled",
                stage="cancelled",
            )
            await db.commit()
        return {"source_id": source_id, "status": "cancelled"}
    except Exception as exc:
        async with resources.session_factory() as db:
            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="failure",
                stage="error",
                error_summary=str(exc),
            )
            await db.commit()
        raise


async def _ensure_floor_buckets(db, source, sid, resources) -> dict | None:
    """Run the zero-LLM section floor over the source's chunks (idempotent).

    Thin worker glue around :func:`course_generator.ensure_section_buckets`:
    loads the chunks in source order and hands them over. Returns the planner
    stats when planning ran, ``None`` when it no-oped (page-structured source,
    buckets already present, or no chunks).
    """
    from sqlalchemy import select

    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.services.course_generator import (
        CourseGenerator,
        ensure_section_buckets,
    )

    rows = (
        await db.execute(
            select(ContentChunkModel).where(ContentChunkModel.source_id == sid)
        )
    ).scalars().all()
    chunks = sorted(rows, key=CourseGenerator._chunk_order_key)
    return await ensure_section_buckets(db, source, chunks, resources.model_router)


async def _maybe_run_agentic_outline(
    db, source, sid, resources, event_bus, target_language: str = "zh-CN"
) -> int | None:
    """Replace the section floor's bucketing with the critic-gated
    video→course outline, in place, before CourseGenerator assembles.

    The graph consolidates the analyzed chunks into a coherent, difficulty-
    ramped, knowledge-point-bearing outline (with a bounded re-plan loop), then
    we project that outline back onto chunk metadata
    (``section_bucket`` / ``section_bucket_topic`` / ``difficulty``) — the exact
    contract CourseGenerator's bucket mode already consumes. So generation /
    lesson-fill / persistence are reused unchanged; only the *bucketing
    decision* moves from the blind zero-LLM floor to a gated agent graph.

    No-ops (returns ``None``) for page-structured sources (PDF/markdown keep
    their page sections) and for sources with fewer than two chunks. Mutates
    chunk metadata and flushes; the caller commits.
    """
    from sqlalchemy import select

    from app.agentcore.llm.router_client import RouterLLMClient
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.services.course_generator import CourseGenerator
    from app.services.llm.router import TaskType, resolve_chain
    from app.services.orchestration.topologies.video_to_course import (
        build_chunk_summaries,
        build_warm_start_buckets,
        plan_video_outline,
        split_oversized_sections,
    )
    from app.services.section_planner import (
        SECTION_BUCKET_KEY,
        SECTION_BUCKET_TOPIC_KEY,
    )

    rows = (
        await db.execute(
            select(ContentChunkModel).where(ContentChunkModel.source_id == sid)
        )
    ).scalars().all()
    chunks = sorted(rows, key=CourseGenerator._chunk_order_key)
    if len(chunks) < 2:
        return None
    # Page-structured sources assemble by page, not by bucket — leave them.
    if any((c.metadata_ or {}).get("page_index") is not None for c in chunks):
        return None

    summaries = build_chunk_summaries(chunks)
    warm = build_warm_start_buckets(chunks)
    chain = resolve_chain(TaskType.PLANNING)
    llm = RouterLLMClient(
        resources.model_router, primary=chain[0], fallbacks=chain[1:]
    )

    sections = await plan_video_outline(
        llm,
        title=source.title or "Untitled",
        chunk_summaries=summaries,
        warm_start_buckets=warm,
        bus=event_bus,
        target_language=target_language,
    )
    if not sections:
        return None

    # Budget guard: the planner optimizes coherence and is blind to the
    # per-lesson token budget, so a dense section can exceed what
    # LessonGenerator ingests (→ silent tail truncation). Re-split oversized
    # sections along chunk boundaries to fit the same budget the lesson
    # generator uses (resolved from the CONTENT_ANALYSIS/lesson provider).
    try:
        from app.services.llm.token_budget import (
            count_tokens,
            lesson_input_token_budget,
        )

        lesson_provider = await resources.model_router.get_provider(
            TaskType.CONTENT_ANALYSIS
        )
        cap = lesson_input_token_budget(lesson_provider)
        token_counts = [count_tokens(c.text or "") for c in chunks]
        sections = split_oversized_sections(sections, token_counts, cap)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Oversized-section split skipped for source %s: %s", sid, exc
        )

    # Project the ordered outline onto contiguous section_bucket ids. The
    # validator guarantees each section is a contiguous chunk range, so bucket
    # ids line up with CourseGenerator's "consecutive chunks share a bucket".
    for bucket_id, section in enumerate(sections):
        title = section.get("title")
        difficulty = section.get("difficulty", 1)
        for idx in section.get("source_chunk_indices", []):
            if 0 <= idx < len(chunks):
                chunk = chunks[idx]
                merged = {**(chunk.metadata_ or {})}
                merged[SECTION_BUCKET_KEY] = bucket_id
                merged[SECTION_BUCKET_TOPIC_KEY] = title
                merged["difficulty"] = difficulty
                chunk.metadata_ = merged
    await db.flush()
    logger.info(
        "Agentic outline: %d sections from %d chunks for source %s",
        len(sections),
        len(chunks),
        sid,
    )
    return len(sections)


def _section_to_critic_dict(section) -> dict:
    """Project a Section row into the RuleCritic input shape."""
    content = section.content or {}
    lesson = content.get("lesson") or {}
    knowledge_points: list[str] = []
    has_practice = False
    for block in lesson.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "concept_relation":
            for concept in block.get("concepts", []):
                label = concept.get("label") if isinstance(concept, dict) else None
                if label:
                    knowledge_points.append(label)
        if block.get("type") == "practice_trigger":
            has_practice = True
    return {
        "title": section.title,
        "difficulty": section.difficulty or 1,
        "knowledge_points": knowledge_points,
        "has_practice": has_practice,
    }


async def _run_course_critic(sections, event_bus, resources) -> None:
    """Run the critic over the assembled course and publish the verdict.

    Uses ``RuleCritic`` (zero-LLM) by default; if a CRITIC route is configured
    and the deployment opts in, ``ModelCritic`` could be substituted here. The
    verdict is emitted as a CUSTOM ``critic_verdict`` AG-UI event (advisory).
    """
    from app.services.orchestration.critic import RuleCritic
    from app.services.orchestration.graph import GraphState

    state = GraphState(
        data={"sections": [_section_to_critic_dict(s) for s in sections]}
    )
    verdict = await RuleCritic().evaluate(state)
    from app.agentcore.events.types import custom

    await event_bus.emit(
        custom(
            "critic_verdict",
            {
                "passed": verdict.passed,
                "scores": verdict.scores,
                "feedback": verdict.feedback,
            },
        )
    )
    logger.info(
        "Course critic verdict: passed=%s scores=%s", verdict.passed, verdict.scores
    )
