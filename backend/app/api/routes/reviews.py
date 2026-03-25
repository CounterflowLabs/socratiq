"""API routes for spaced repetition review items."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.db.models.user import User
from app.services.spaced_repetition import SpacedRepetitionService

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


class ReviewItemResponse(BaseModel):
    id: uuid.UUID
    concept_id: uuid.UUID
    exercise_id: uuid.UUID | None
    easiness: float
    interval_days: int
    repetitions: int
    review_at: datetime
    last_reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class DueReviewsResponse(BaseModel):
    items: list[ReviewItemResponse]
    total: int


class CompleteReviewRequest(BaseModel):
    quality: int  # 0-5


class CompleteReviewResponse(BaseModel):
    id: uuid.UUID
    new_interval_days: int
    new_repetitions: int
    next_review_at: datetime


class ReviewStatsResponse(BaseModel):
    due_today: int
    completed_today: int


@router.get("/due", response_model=DueReviewsResponse)
async def get_due_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    limit: int = 20,
) -> DueReviewsResponse:
    """Get review items due for the current user."""
    srs = SpacedRepetitionService(db)
    items = await srs.get_due_reviews(user_id=user.id, limit=limit)

    return DueReviewsResponse(
        items=[
            ReviewItemResponse(
                id=item.id,
                concept_id=item.concept_id,
                exercise_id=item.exercise_id,
                easiness=float(item.easiness),
                interval_days=item.interval_days,
                repetitions=item.repetitions,
                review_at=item.review_at,
                last_reviewed_at=item.last_reviewed_at,
            )
            for item in items
        ],
        total=len(items),
    )


@router.post("/{review_id}/complete", response_model=CompleteReviewResponse)
async def complete_review(
    review_id: uuid.UUID,
    request: CompleteReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> CompleteReviewResponse:
    """Complete a review with a quality rating (0-5). Uses optimistic locking."""
    if not (0 <= request.quality <= 5):
        raise HTTPException(422, "quality must be between 0 and 5")

    srs = SpacedRepetitionService(db)
    updated = await srs.complete_review(
        review_id=review_id,
        user_id=user.id,
        quality=request.quality,
    )

    if updated is None:
        raise HTTPException(
            404,
            "Review item not found, does not belong to user, or was concurrently updated",
        )

    return CompleteReviewResponse(
        id=updated.id,
        new_interval_days=updated.interval_days,
        new_repetitions=updated.repetitions,
        next_review_at=updated.review_at,
    )


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_review_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> ReviewStatsResponse:
    """Get review stats: due today and completed today."""
    srs = SpacedRepetitionService(db)
    stats = await srs.get_stats(user_id=user.id)
    return ReviewStatsResponse(
        due_today=stats["due_today"],
        completed_today=stats["completed_today"],
    )
