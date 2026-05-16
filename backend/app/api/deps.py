import uuid
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import async_session_factory, engine
from app.db.models.user import User
from app.services.activation import has_active_subscription
from app.services.auth import AuthService
from app.services.llm.router import ModelRouter

LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Paths that authenticated users without an active subscription can still hit:
# auth-related endpoints, the redemption endpoint itself, basic profile, and
# health. Anything else 402s until the user redeems a code.
_PAYWALL_BYPASS_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/activation/",
    "/health",
)


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


def _auth_service() -> AuthService:
    s = get_settings()
    return AuthService(
        secret_key=s.jwt_secret_key,
        access_expire_minutes=s.jwt_access_expire_minutes,
        refresh_expire_days=s.jwt_refresh_expire_days,
    )


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Authorization: Bearer JWT.

    In offline / dev mode (`AUTH_MODE=local`), returns the fixed local user
    without requiring a token — useful for backend smoke tests and the
    legacy single-user setup. In any other mode, a valid access token is
    required.
    """
    settings = get_settings()
    if settings.auth_mode == "local":
        return await _get_or_create_local_user(db)

    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = _auth_service().verify_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not an access token",
        )
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Paywall gate: outside the bypass list, require an active subscription.
    path = request.url.path
    if not any(path.startswith(p) for p in _PAYWALL_BYPASS_PREFIXES):
        if not is_admin_user(user) and not has_active_subscription(user):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "subscription_required",
                    "message": "Redeem an activation code to continue.",
                },
            )

    return user


def is_admin_user(user: User) -> bool:
    """Check membership in the ADMIN_EMAILS allowlist."""
    admin_emails = {
        e.strip().lower()
        for e in (get_settings().admin_emails or "").split(",")
        if e.strip()
    }
    return user.email.lower() in admin_emails


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


async def require_budget(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Enforce the user's monthly USD spend cap.

    Apply to LLM-heavy entry points (chat, source ingest, course
    regeneration, diagnostic / exercise generation). Returns the user on
    success; raises 429 with a structured `quota_exceeded` payload when
    the cap is hit.
    """
    if is_admin_user(user):
        return user
    from app.services.cost_guard import CostGuard  # local import to avoid cycle

    guard = CostGuard(db)
    ok, spent, cap = await guard.check_user_budget_usd(user)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "quota_exceeded",
                "message": "已达本月用量上限，请联系运营或升级套餐。",
                "spent_usd": round(spent, 4),
                "cap_usd": cap,
            },
        )
    return user


async def _get_or_create_local_user(db: AsyncSession) -> User:
    user = await db.get(User, LOCAL_USER_ID)
    if not user:
        user = User(id=LOCAL_USER_ID, email="local@socratiq.local", name="Local User")
        db.add(user)
        await db.flush()
    return user


# Backwards-compatible alias. New code should import get_current_user instead.
get_local_user = get_current_user
