"""Course generation Celery task — assembles courses from persisted source assets."""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.services.llm.router import ModelRouter
from app.services.source_tasks import mark_source_task
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
    name="course_generation.generate_course",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=600,
    time_limit=660,
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
    return asyncio.run(_generate_course_async(self, source_id, user_id))


async def _generate_course_async(task, source_id: str, user_id: str | None) -> dict:
    """Async implementation of course generation."""
    from sqlalchemy import select
    from app.db.models.course import Section
    from app.db.models.lab import Lab
    from app.db.models.source import Source
    from app.services.course_generator import CourseGenerator

    resources = _create_worker_resources()

    sid = UUID(source_id)
    uid = UUID(user_id) if user_id else None

    try:
        async with resources.session_factory() as db:
            source = await db.get(Source, sid)
            if not source or source.status != "ready":
                raise ValueError(f"Source {source_id} not ready for course generation")

            await mark_source_task(
                db,
                source_id=sid,
                task_type="course_generation",
                status="running",
                stage="assembling_course",
            )
            task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})

            generator = CourseGenerator(resources.model_router)
            course = await generator.generate(
                db=db,
                source_ids=[sid],
                title=source.title,
                user_id=uid,
                skip_ready_check=True,
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
    finally:
        await resources.engine.dispose()
