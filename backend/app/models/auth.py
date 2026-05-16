"""Pydantic schemas for the auth endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GoogleLoginRequest(BaseModel):
    id_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User info returned to the frontend after login / on /me."""

    id: UUID
    email: str
    name: str | None = None
    avatar_url: str | None = None
    is_admin: bool = False
    subscription_until: datetime | None = None
    monthly_usd_cap: float | None = None
    has_active_subscription: bool = False


class LoginResponse(BaseModel):
    user: UserResponse
    tokens: TokenPair
