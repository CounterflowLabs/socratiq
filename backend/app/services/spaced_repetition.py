"""Spaced repetition service implementing SM-2 algorithm."""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update as sa_update, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SpacedRepetitionService:
    def __init__(self, db: AsyncSession | None = None):
        self._db = db

    @staticmethod
    def calculate(
        quality: int, easiness: float, interval_days: int, repetitions: int,
    ) -> tuple[float, int, int]:
        """Pure SM-2 calculation. Returns (new_easiness, new_interval, new_reps)."""
        new_easiness = max(
            1.3,
            easiness + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02),
        )
        if quality >= 3:
            if repetitions == 0:
                new_interval = 1
            elif repetitions == 1:
                new_interval = 6
            else:
                new_interval = round(interval_days * new_easiness)
            new_reps = repetitions + 1
        else:
            new_interval = 1
            new_reps = 0
        return new_easiness, new_interval, new_reps

    async def get_due_reviews(self, user_id: UUID, limit: int = 20):
        from app.db.models.review_item import ReviewItem
        result = await self._db.execute(
            select(ReviewItem)
            .where(ReviewItem.user_id == user_id, ReviewItem.review_at <= datetime.utcnow())
            .order_by(ReviewItem.review_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def complete_review(self, review_id: UUID, user_id: UUID, quality: int):
        from app.db.models.review_item import ReviewItem
        item = await self._db.get(ReviewItem, review_id)
        if not item or item.user_id != user_id:
            return None
        expected_reps = item.repetitions
        new_e, new_i, new_r = self.calculate(
            quality=quality, easiness=float(item.easiness),
            interval_days=item.interval_days, repetitions=item.repetitions,
        )
        result = await self._db.execute(
            sa_update(ReviewItem)
            .where(ReviewItem.id == review_id, ReviewItem.repetitions == expected_reps)
            .values(
                easiness=new_e, interval_days=new_i, repetitions=new_r,
                review_at=datetime.utcnow() + timedelta(days=new_i),
                last_reviewed_at=datetime.utcnow(),
            )
            .returning(ReviewItem)
        )
        return result.scalar_one_or_none()

    async def get_or_create_review(self, user_id: UUID, concept_id: UUID, exercise_id: UUID | None = None):
        from app.db.models.review_item import ReviewItem
        result = await self._db.execute(
            select(ReviewItem).where(ReviewItem.user_id == user_id, ReviewItem.concept_id == concept_id)
        )
        item = result.scalar_one_or_none()
        if item:
            return item
        item = ReviewItem(
            user_id=user_id, concept_id=concept_id, exercise_id=exercise_id,
            review_at=datetime.utcnow() + timedelta(days=1),
        )
        self._db.add(item)
        await self._db.flush()
        return item

    async def get_stats(self, user_id: UUID) -> dict:
        from app.db.models.review_item import ReviewItem
        due = await self._db.execute(
            select(func.count(ReviewItem.id)).where(
                ReviewItem.user_id == user_id, ReviewItem.review_at <= datetime.utcnow()
            )
        )
        completed = await self._db.execute(
            select(func.count(ReviewItem.id)).where(
                ReviewItem.user_id == user_id,
                ReviewItem.last_reviewed_at >= datetime.utcnow() - timedelta(days=1),
            )
        )
        return {"due_today": due.scalar() or 0, "completed_today": completed.scalar() or 0}
