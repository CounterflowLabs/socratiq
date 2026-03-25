"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, _get_auth_service
from app.db.models.user import User
from app.services.auth import AuthService, maybe_claim_demo_data

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class ExchangeRequest(BaseModel):
    provider: str  # "google", "github", "credentials"
    id_token: str | None = None
    email: str | None = None
    password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    avatar_url: str | None
    oauth_provider: str | None


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    request: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthService, Depends(_get_auth_service)],
):
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")

    user = User(
        email=request.email,
        name=request.name,
        hashed_password=auth.hash_password(request.password),
    )
    db.add(user)
    await db.flush()

    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.email),
        refresh_token=auth.create_refresh_token(user.id),
    )


@router.post("/exchange", response_model=TokenResponse)
async def exchange(
    request: ExchangeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthService, Depends(_get_auth_service)],
):
    user = None

    if request.provider == "credentials":
        if not request.email or not request.password:
            raise HTTPException(400, "Email and password required")
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
        if not user or not user.hashed_password:
            raise HTTPException(401, "Invalid credentials")
        if not auth.verify_password(request.password, user.hashed_password):
            raise HTTPException(401, "Invalid credentials")

    elif request.provider == "google":
        if not request.id_token:
            raise HTTPException(400, "id_token required for Google login")
        from app.config import get_settings
        google_info = await auth.verify_google_token(
            request.id_token, get_settings().google_client_id
        )
        result = await db.execute(
            select(User).where(
                User.oauth_provider == "google",
                User.oauth_id == google_info["sub"],
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            result = await db.execute(
                select(User).where(User.email == google_info["email"])
            )
            user = result.scalar_one_or_none()
            if user:
                user.oauth_provider = "google"
                user.oauth_id = google_info["sub"]
                user.avatar_url = google_info.get("picture")
            else:
                user = User(
                    email=google_info["email"],
                    name=google_info.get("name"),
                    oauth_provider="google",
                    oauth_id=google_info["sub"],
                    avatar_url=google_info.get("picture"),
                )
                db.add(user)
        await db.flush()

    else:
        raise HTTPException(400, f"Unsupported provider: {request.provider}")

    if not user or not user.is_active:
        raise HTTPException(403, "Account is disabled")

    await maybe_claim_demo_data(user.id, db)

    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.email),
        refresh_token=auth.create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthService, Depends(_get_auth_service)],
):
    try:
        payload = auth.verify_token(request.refresh_token)
    except ValueError as e:
        raise HTTPException(401, str(e))

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    from uuid import UUID
    user = await db.get(User, UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")

    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.email),
        refresh_token=auth.create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        oauth_provider=user.oauth_provider,
    )
