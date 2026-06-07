"""Sentence→course generation task — a full course from a single prompt.

This is the back-half entry point of the sentence→course pipeline. Unlike
``generate_course`` (which assembles from a persisted, chunk-bearing Source via
``CourseGenerator``), this path has NO source material: it explores an outline
from a one-sentence prompt, freezes it through the critic gate, then fills each
section with a SOURCE-LESS lesson drawn from the LLM's own topic knowledge, and
persists a ``Course`` + ``Section`` rows directly (no ``CourseGenerator``).

Wrapped in an AG-UI run (run_started/finished/error + a Redis event stream) so
the web process can re-stream live progress over SSE, mirroring
``generate_course``.
"""

from __future__ import annotations

import logging
import uuid

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

logger = logging.getLogger(__name__)


async def generate_sentence_course(
    ctx: dict,
    prompt: str,
    user_id: str | None = None,
    target_language: str = "zh-CN",
) -> dict:
    """Generate a full course from a single one-sentence ``prompt``.

    Args:
        ctx: ARQ job context (carries shared ``resources`` and ``job_id``).
        prompt: The one-sentence learning request.
        user_id: Optional owner UUID string for the resulting course.
        target_language: Language for generated titles / prose.

    Returns:
        ``{"course_id": str, "status": "ready", ...}``.
    """
    run_id = ctx.get("job_id") or str(uuid.uuid4())
    # The AG-UI ``thread_id`` is the conceptual conversation; with no source we
    # use the run id itself so the frontend can subscribe by the task id.
    thread_id = run_id
    redis = aioredis.from_url(get_settings().redis_url)
    bus = EventBus(
        thread_id=thread_id,
        run_id=run_id,
        sinks=[RedisEventSink(redis, run_id), TracerEventSink()],
    )
    await bus.emit(run_started(thread_id=thread_id, run_id=run_id))
    try:
        result = await _generate_sentence_course_async(
            prompt=prompt,
            user_id=user_id,
            target_language=target_language,
            resources=ctx["resources"],
            event_bus=bus,
        )
    except Exception as exc:  # noqa: BLE001
        await bus.emit(run_error(message=str(exc)))
        await bus.aclose()
        await redis.aclose()
        raise
    await bus.emit(run_finished(thread_id=thread_id, run_id=run_id, result=result))
    await bus.aclose()
    await redis.aclose()
    return result


async def _generate_sentence_course_async(
    *,
    prompt: str,
    user_id: str | None,
    target_language: str,
    resources,
    event_bus=None,
) -> dict:
    """Explore → freeze outline → source-less fill → persist Course + Sections."""
    from app.agentcore.llm.router_client import RouterLLMClient
    from app.db.models.course import Course, Section
    from app.services.llm.router import TaskType, resolve_chain
    from app.services.orchestration.graph import GraphState
    from app.services.orchestration.topologies.sentence_to_course import (
        build_sentence_course_graph,
        fill_sentence_course,
    )
    from app.services.sentence_lesson_generator import SentenceLessonGenerator

    uid = uuid.UUID(user_id) if user_id else None

    # Front half: explore + critic-gated freeze. The PLANNING chain shapes the
    # outline; resolve_chain degrades to a provisioned route if PLANNING itself
    # is unconfigured.
    chain = resolve_chain(TaskType.PLANNING)
    planner_llm = RouterLLMClient(
        resources.model_router, primary=chain[0], fallbacks=chain[1:]
    )
    state = GraphState(data={"prompt": prompt})
    graph = build_sentence_course_graph(planner_llm)
    state = await graph.execute(state, bus=event_bus)

    sections = state.data.get("sections") or []
    if not sections:
        raise ValueError(
            "Sentence outline produced no sections; cannot generate course"
        )

    # Back half: a SOURCE-LESS lesson per section, generated in parallel. The
    # generator drives one concrete provider (the PLANNING chain's first
    # resolvable one) directly via AgentRuntime.
    provider = await _resolve_first_provider(resources.model_router, chain)
    generator = SentenceLessonGenerator(provider)
    filled = await fill_sentence_course(
        generator, sections, target_language=target_language, bus=event_bus
    )

    # Persist a fresh Course + ordered Sections. Each Section carries the
    # block-based lesson under ``content["lesson"]`` — the exact shape the
    # frontend renders and the same key chunk-based generation uses.
    title = _course_title(prompt)
    async with resources.session_factory() as db:
        course = Course(
            title=title,
            description=prompt.strip() or None,
            created_by=uid,
        )
        db.add(course)
        await db.flush()  # assign course.id

        persisted = 0
        for order_index, entry in enumerate(filled):
            lesson = entry.get("lesson")
            content: dict = {"lesson": lesson} if lesson else {}
            if entry.get("error"):
                content["lesson_generation_error"] = entry["error"]
            section = Section(
                course_id=course.id,
                title=entry.get("title") or f"Section {order_index + 1}",
                order_index=order_index,
                content=content,
                difficulty=entry.get("difficulty", 1),
            )
            if entry.get("error") and not lesson:
                section.lesson_generation_error = entry["error"]
            db.add(section)
            if lesson:
                persisted += 1

        await db.commit()
        course_id = str(course.id)

    logger.info(
        "Generated sentence course '%s' (%s): %d/%d sections with lessons",
        title,
        course_id,
        persisted,
        len(filled),
    )
    return {
        "course_id": course_id,
        "title": title,
        "sections_created": len(filled),
        "lessons_created": persisted,
        "status": "ready",
    }


async def _resolve_first_provider(router, chain):
    """Resolve the first provider in ``chain`` that has a configured route.

    Mirrors ``RouterLLMClient._resolve`` so the source-less generator gets the
    same primary the planner would have used, degrading through the fallback
    chain if PLANNING itself is unconfigured.
    """
    from app.services.llm.base import LLMError

    last: Exception | None = None
    for task in chain:
        try:
            return await router.get_provider(task)
        except LLMError as exc:
            last = exc
    raise last or LLMError("no provider could be resolved for sentence fill")


def _course_title(prompt: str) -> str:
    """Derive a short course title from the one-sentence prompt."""
    text = " ".join((prompt or "").split()).strip()
    if not text:
        return "Untitled course"
    # Keep it title-length; sentence prompts are usually short already.
    return text if len(text) <= 80 else text[:77].rstrip() + "…"
