"""Pydantic schemas for activation-code endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RedeemRequest(BaseModel):
    code: str


class SubscriptionStatus(BaseModel):
    has_active_subscription: bool
    subscription_until: datetime | None = None
    monthly_usd_cap: float | None = None
    tier: str | None = None


class RedeemResponse(BaseModel):
    code: str
    tier: str
    subscription_until: datetime
    monthly_usd_cap: float


class ActivationCodeAdminView(BaseModel):
    """Admin-facing view of a generated code (CLI / admin tooling)."""

    id: UUID
    code: str
    tier: str
    valid_days: int
    monthly_usd_cap: float
    note: str | None
    redeemed_by_user_id: UUID | None
    redeemed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
