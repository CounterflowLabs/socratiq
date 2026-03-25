from collections.abc import AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import async_session_factory, engine
from app.db.models.user import User
from app.services.auth import AuthService
from app.services.llm.router import ModelRouter


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


def _get_auth_service() -> AuthService:
    """Create an AuthService from application settings."""
    settings = get_settings()
    return AuthService(
        secret_key=settings.jwt_secret_key,
        access_expire_minutes=settings.jwt_access_expire_minutes,
        refresh_expire_days=settings.jwt_refresh_expire_days,
    )


async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT from Authorization header, return User."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    auth_service = _get_auth_service()
    try:
        payload = auth_service.verify_token(token)
    except ValueError as e:
        raise HTTPException(401, str(e))

    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")

    user = await db.get(User, UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")

    return user
