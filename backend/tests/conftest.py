"""Test configuration and fixtures."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models.base import Base
import app.db.models  # noqa: F401 -- register all models
from app.api.deps import get_db, get_redis, get_model_router, get_local_user, LOCAL_USER_ID
from app.db.models.user import User
from app.services.llm.base import LLMResponse, ContentBlock, StreamChunk, LLMProvider
from app.services.llm.router import ModelRouter
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session using the dev database.

    Uses a connection-level transaction + SAVEPOINT so that route handlers
    can call ``await session.commit()`` without actually committing; the
    outer transaction is always rolled back at the end of the test.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Open a connection and begin a transaction that we will roll back
    connection = await engine.connect()
    transaction = await connection.begin()

    # Keep tests isolated from rows that already exist in the shared dev DB.
    tables = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    if tables:
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    # Bind a session to this connection; every commit becomes a SAVEPOINT
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    yield session

    # Teardown: roll back the outer transaction so nothing persists
    await session.close()
    if transaction.is_active:
        await transaction.rollback()
    await connection.close()
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


@pytest_asyncio.fixture
async def demo_user(db_session):
    """Insert the local user for offline mode."""
    user = User(
        id=LOCAL_USER_ID,
        email="local@socratiq.local",
        name="Local User",
    )
    db_session.add(user)
    await db_session.flush()
    return user
