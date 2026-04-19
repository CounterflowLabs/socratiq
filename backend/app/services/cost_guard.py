"""LLM usage tracking and budget enforcement."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.llm_usage_log import LlmUsageLog

DEFAULT_LIMITS = {
    "diagnostic": 50_000,
    "exercise_gen": 50_000,
    "grading": 50_000,
    "translation": 100_000,
    "memory": 20_000,
    "mentor_chat": 200_000,
}


class CostGuard:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def log_usage(
        self, user_id: UUID, task_type: str,
        model_name: str, tokens_in: int, tokens_out: int,
    ) -> None:
        cost = (tokens_in * 0.000003) + (tokens_out * 0.000015)
        log = LlmUsageLog(
            user_id=user_id, task_type=task_type,
            model_name=model_name, tokens_in=tokens_in,
            tokens_out=tokens_out, estimated_cost_usd=cost,
        )
        self._db.add(log)
        await self._db.flush()

    async def check_budget(self, user_id: UUID, task_type: str) -> bool:
        limit = DEFAULT_LIMITS.get(task_type, 100_000)
        since = datetime.utcnow() - timedelta(days=1)
        result = await self._db.execute(
            select(func.coalesce(func.sum(LlmUsageLog.tokens_in + LlmUsageLog.tokens_out), 0))
            .where(
                LlmUsageLog.user_id == user_id,
                LlmUsageLog.task_type == task_type,
                LlmUsageLog.created_at >= since,
            )
        )
        total = result.scalar()
        return total < limit
