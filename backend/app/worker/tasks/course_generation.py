"""Course generation Celery task — assembles courses from persisted source assets."""

import logging
from uuid import UUID

from app.services.source_tasks import mark_source_task
from app.worker.celery_app import celery_app
from app.worker.resources import _create_worker_resources

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="course_generation.generate_course",
    max_retries=1,
    default_retry_delay=30,
)
def generate_course_task(
    self,
    ingest_result: dict,
    user_id: str | None = None,
    goal: str | None = None,
) -> dict:
    """Generate course from an ingested source.

    Args:
        ingest_result: Result dict from ingest_source or clone_source (contains source_id).
        user_id: User UUID string for course ownership.
        goal: Legacy compatibility kwarg from older producers; ignored by the worker.
    """
    import asyncio

    source_id = ingest_result["source_id"]

    async def _runner():
        resources = _create_worker_resources()
        try:
            return await _generate_course_async(self, source_id, user_id, resources)
        finally:
            await resources.engine.dispose()

    return asyncio.run(_runner())


async def _generate_course_async(
    task, source_id: str, user_id: str | None, resources
) -> dict:
    """Async implementation of course generation."""
    from sqlalchemy import select
    from app.db.models.course import Section
    from app.db.models.lab import Lab
    from app.db.models.source import Source
    from app.db.models.source_task import SourceTask
    from app.services.course_generator import CourseGenerator

    sid = UUID(source_id)
    uid = UUID(user_id) if user_id else None

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
                logger.info(
                    "Skipping course generation for %s: already produced %s",
                    source_id,
                    existing_task.metadata_["course_id"],
                )
                return {
                    "source_id": source_id,
                    "course_id": existing_task.metadata_["course_id"],
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
