"""Test configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models.base import Base
import app.db.models  # noqa: F401 — register all models
from app.api.deps import get_db, get_redis
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session using the dev database.

    Uses the real database from settings. For CI, use testcontainers.
    Each test gets a transaction that is rolled back after the test.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client with dependency overrides."""

    async def _override_db():
        yield db_session

    async def _override_redis():
        import fakeredis.aioredis
        client = fakeredis.aioredis.FakeRedis()
        try:
            yield client
        finally:
            await client.aclose()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
