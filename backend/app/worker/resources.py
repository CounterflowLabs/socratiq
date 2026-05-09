"""Worker-process-level shared resources (DB engine + ModelRouter).

The Celery worker initializes a single ``WorkerResources`` per child process via
the ``worker_process_init`` signal (see ``celery_app.py``) and disposes it via
``worker_process_shutdown``. Tasks call ``get_worker_resources()`` to acquire
the cached bundle instead of paying TCP/handshake cost on every call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.services.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResources:
    """Worker-process-level resources shared by all tasks in this process."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    model_router: ModelRouter


_resources: WorkerResources | None = None


def _create_worker_resources() -> WorkerResources:
    """Build a fresh resources bundle. Public for tests; production goes through init."""
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


def init_worker_resources() -> None:
    """Initialize the per-process singleton. Idempotent."""
    global _resources
    if _resources is not None:
        return
    _resources = _create_worker_resources()
    logger.info("Worker resources initialized")


async def dispose_worker_resources() -> None:
    """Dispose the singleton's engine. Idempotent."""
    global _resources
    if _resources is None:
        return
    await _resources.engine.dispose()
    _resources = None
    logger.info("Worker resources disposed")


def get_worker_resources() -> WorkerResources:
    """Return the singleton, lazily initializing if not yet set up.

    Lazy fallback covers Celery eager-mode tests and direct invocation paths
    where ``worker_process_init`` was never fired.
    """
    global _resources
    if _resources is None:
        _resources = _create_worker_resources()
    return _resources


def reset_worker_resources_for_test() -> None:
    """Test-only: drop the singleton without disposing the engine.

    Used by unit tests that monkeypatch the factory's collaborators and need
    each call to ``_create_worker_resources`` to observe the patches.
    """
    global _resources
    _resources = None
