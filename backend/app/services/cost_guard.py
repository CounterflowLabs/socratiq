"""LLM usage tracking and budget enforcement."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.llm_usage_log import LlmUsageLog
from app.db.models.user import User


# Fallback per-task daily token budgets when a user has no monthly USD cap
# configured (i.e. demo / admin path).
DEFAULT_LIMITS = {
    "diagnostic": 50_000,
    "exercise_gen": 50_000,
    "grading": 50_000,
    "translation": 100_000,
    "memory": 20_000,
    "mentor_chat": 200_000,
    "course_regeneration": 500_000,
}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class CostGuard:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def log_usage(
        self,
        user_id: UUID,
        task_type: str,
        model_name: str,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        cost = (tokens_in * 0.000003) + (tokens_out * 0.000015)
        log = LlmUsageLog(
            user_id=user_id,
            task_type=task_type,
            model_name=model_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=cost,
        )
        self._db.add(log)
        await self._db.flush()

    async def check_budget(self, user_id: UUID, task_type: str) -> bool:
        """Legacy per-task daily token check. Retained for callers that
        haven't migrated to the per-user monthly USD cap yet."""
        limit = DEFAULT_LIMITS.get(task_type, 100_000)
        since = _utcnow_naive() - timedelta(days=1)
        result = await self._db.execute(
            select(
                func.coalesce(
                    func.sum(LlmUsageLog.tokens_in + LlmUsageLog.tokens_out), 0
                )
            ).where(
                LlmUsageLog.user_id == user_id,
                LlmUsageLog.task_type == task_type,
                LlmUsageLog.created_at >= since,
            )
        )
        total = result.scalar()
        return total < limit

    async def monthly_spend_usd(self, user_id: UUID) -> float:
        """Sum estimated_cost_usd for the user since the start of this month."""
        since = _month_start(_utcnow_naive())
        result = await self._db.execute(
            select(
                func.coalesce(func.sum(LlmUsageLog.estimated_cost_usd), 0)
            ).where(
                LlmUsageLog.user_id == user_id,
                LlmUsageLog.created_at >= since,
            )
        )
        total = result.scalar() or 0
        return float(total)

    async def check_user_budget_usd(self, user: User) -> tuple[bool, float, float | None]:
        """Return (ok, spent_usd, cap_usd_or_none).

        - If the user has no monthly cap (admin / demo), allow.
        - Otherwise compare current-month estimated spend against the cap.
        """
        if user.monthly_usd_cap is None:
            return True, 0.0, None
        cap = float(user.monthly_usd_cap)
        spent = await self.monthly_spend_usd(user.id)
        return spent < cap, spent, cap
