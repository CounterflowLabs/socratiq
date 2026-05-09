"""Per-task worker resources factory (DB engine + ModelRouter).

Each Celery task invocation owns its own ``WorkerResources`` because Celery's
prefork pool creates a fresh ``asyncio.run`` per task, and asyncpg connection
pools are loop-bound — sharing them across loops yields
``InterfaceError: another operation is in progress``.

The lifecycle is therefore:

    resources = _create_worker_resources()
    try:
        ... use resources.session_factory / model_router ...
    finally:
        await resources.engine.dispose()
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.services.llm.router import ModelRouter


@dataclass(frozen=True)
class WorkerResources:
    """Loop-local resources for a single Celery task run."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    model_router: ModelRouter


def _create_worker_resources() -> WorkerResources:
    """Build a fresh resources bundle bound to the current event loop."""
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
