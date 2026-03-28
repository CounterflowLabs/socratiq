import uuid
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import async_session_factory, engine
from app.db.models.user import User
from app.services.llm.router import ModelRouter

LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = aioredis.from_url(get_settings().redis_url)
    try:
        yield client
    finally:
        await client.aclose()


_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get the singleton ModelRouter instance."""
    global _model_router
    if _model_router is None:
        settings = get_settings()
        _model_router = ModelRouter(
            session_factory=async_session_factory,
            encryption_key=settings.llm_encryption_key,
        )
    return _model_router


async def get_local_user(db: AsyncSession = Depends(get_db)) -> User:
    """Return the fixed local user (offline mode, no auth)."""
    user = await db.get(User, LOCAL_USER_ID)
    if not user:
        user = User(id=LOCAL_USER_ID, email="local@socratiq.local", name="Local User")
        db.add(user)
        await db.flush()
    return user
