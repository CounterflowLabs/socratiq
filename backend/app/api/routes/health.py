from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.api.deps import get_db, get_redis

router = APIRouter()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    status = {"status": "ok", "db": "ok", "redis": "ok"}

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        status["db"] = "error"
        status["status"] = "degraded"

    try:
        await redis_client.ping()
    except Exception:
        status["redis"] = "error"
        status["status"] = "degraded"

    return status
