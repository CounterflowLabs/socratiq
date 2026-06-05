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
                stage="assembling_course",
            )
            task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})

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
