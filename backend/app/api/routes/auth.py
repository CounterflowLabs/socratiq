"""Authentication endpoints: Google SSO login, token refresh, current user."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import _auth_service, get_current_user, get_db, is_admin_user
from app.config import get_settings
from app.db.models.user import User
from app.models.auth import (
    GoogleLoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
    UserResponse,
)
from app.services.activation import has_active_subscription
from app.services.auth import AuthService, maybe_claim_demo_data

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        is_admin=is_admin_user(user),
        subscription_until=user.subscription_until,
        monthly_usd_cap=float(user.monthly_usd_cap) if user.monthly_usd_cap is not None else None,
        has_active_subscription=has_active_subscription(user),
    )


@router.post("/google", response_model=LoginResponse)
async def google_login(
    req: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Exchange a Google ID token for our own JWT pair.

    Verifies the Google ID token, upserts a `User` keyed by Google `sub`,
    transfers any leftover demo-user data on first login, and returns an
    access/refresh token pair.
    """
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured on this server",
        )

    try:
        idinfo = await AuthService.verify_google_token(
            req.id_token, settings.google_client_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    google_sub = idinfo["sub"]
    email = idinfo["email"]

    result = await db.execute(
        select(User).where(
            User.oauth_provider == "google",
            User.oauth_id == google_sub,
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        # Also match by email — lets a user who used the demo account by email
        # before adopting Google SSO keep their data.
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=email,
            name=idinfo.get("name") or None,
            avatar_url=idinfo.get("picture") or None,
            oauth_provider="google",
            oauth_id=google_sub,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await maybe_claim_demo_data(user.id, db)
    else:
        # Link existing user to Google if not already linked, refresh profile.
        if not user.oauth_provider:
            user.oauth_provider = "google"
            user.oauth_id = google_sub
        if idinfo.get("name") and not user.name:
            user.name = idinfo["name"]
        if idinfo.get("picture"):
            user.avatar_url = idinfo["picture"]
        await db.flush()

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    auth = _auth_service()
    tokens = TokenPair(
        access_token=auth.create_access_token(user.id, user.email),
        refresh_token=auth.create_refresh_token(user.id),
    )
    return LoginResponse(user=_serialize_user(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    auth = _auth_service()
    try:
        payload = auth.verify_token(req.refresh_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a refresh token",
        )
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return TokenPair(
        access_token=auth.create_access_token(user.id, user.email),
        refresh_token=auth.create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _serialize_user(user)
