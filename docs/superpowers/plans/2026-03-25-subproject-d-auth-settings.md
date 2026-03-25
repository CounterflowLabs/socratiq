# Sub-project D: User Auth + Settings UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded demo user with production-grade authentication (BFF pattern with Auth.js + backend JWT), add multi-tenant user scoping to all routes, and enhance the Settings UI with model creation forms.

**Architecture:** Auth.js on the Next.js server handles OAuth (Google/GitHub) and email/password login, exchanges tokens with the FastAPI backend via `POST /auth/exchange`. The backend signs JWTs (access 15min + refresh 7d). All browser-to-API calls are proxied through Next.js server routes (BFF pattern) — the browser never touches JWTs. Existing routes are migrated to `/api/v1/` prefix and scoped by `user_id`.

**Tech Stack:** Auth.js (NextAuth v5), PyJWT, bcrypt, google-auth, structlog, sentry-sdk

**Spec:** `docs/superpowers/specs/2026-03-25-phase2-design.md` (Sub-project D sections + Cross-Cutting Concerns 0.1-0.4)

---

## File Map

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/auth.py` | JWT sign/verify, password hash/verify, OAuth token validation |
| `backend/app/api/routes/auth.py` | `/auth/register`, `/auth/exchange`, `/auth/refresh`, `/auth/me` |
| `backend/app/api/middleware/correlation.py` | Add correlation_id to every request |
| `backend/app/api/middleware/rate_limit.py` | Redis-based rate limiter |
| `backend/app/services/cost_guard.py` | LLM usage logging + budget enforcement |
| `backend/tests/test_auth.py` | Auth endpoint tests |
| `backend/tests/test_user_scoping.py` | User isolation tests for all routes |
| `backend/alembic/versions/xxx_add_auth_fields.py` | User table migration |
| `backend/alembic/versions/xxx_add_model_user_id.py` | Multi-tenant model configs |
| `backend/alembic/versions/xxx_add_llm_usage_logs.py` | Cost tracking table |

### Backend — Modified Files

| File | Changes |
|------|---------|
| `backend/app/main.py` | Mount v1 router, add middleware (CORS, correlation_id, rate_limit) |
| `backend/app/api/deps.py` | Add `get_current_user` dependency |
| `backend/app/config.py` | Add `jwt_secret_key`, `sentry_dsn`, auth settings |
| `backend/app/db/models/user.py` | Add oauth_provider, oauth_id, avatar_url, hashed_password, is_active |
| `backend/app/api/routes/sources.py` | Prefix `/api/v1/sources`, add user scoping |
| `backend/app/api/routes/courses.py` | Prefix `/api/v1/courses`, add user scoping |
| `backend/app/api/routes/chat.py` | Remove DEMO_USER_ID, use `get_current_user` |
| `backend/app/api/routes/models.py` | Prefix, add user_id filtering |
| `backend/app/api/routes/model_routes.py` | Prefix, add user_id filtering |
| `backend/app/api/routes/tasks.py` | Prefix |
| `backend/app/api/routes/health.py` | Prefix |
| `backend/pyproject.toml` | Add PyJWT, bcrypt, google-auth, structlog, sentry-sdk |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/src/lib/auth.ts` | Auth.js config (providers, callbacks, JWT exchange) |
| `frontend/src/app/api/auth/[...nextauth]/route.ts` | Auth.js catch-all route handler |
| `frontend/src/app/api/v1/[...proxy]/route.ts` | BFF proxy: forwards to FastAPI with JWT header |
| `frontend/src/app/login/page.tsx` | Login page (OAuth buttons + email form) |
| `frontend/src/components/auth-guard.tsx` | Protected route wrapper |
| `frontend/src/middleware.ts` | Redirect unauthenticated users to /login |

### Frontend — Modified Files

| File | Changes |
|------|---------|
| `frontend/package.json` | Add `next-auth` |
| `frontend/src/lib/api.ts` | Change `API_BASE` from `/api` to `/api/v1` |
| `frontend/src/app/settings/page.tsx` | Add account section + model creation form + route editor |
| `frontend/src/lib/stores.ts` | Add `useAuthStore` (optional, may use Auth.js `useSession`) |

---

## Tasks

### Task 1: Backend dependencies + config + structured logging

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Create: `backend/app/api/middleware/correlation.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add to `[project] dependencies`:
```toml
    # Auth
    "PyJWT>=2.8",
    "bcrypt>=4.0",
    "google-auth>=2.0",

    # Observability
    "structlog>=24.0",
    "sentry-sdk[fastapi]>=2.0",
```

- [ ] **Step 2: Add auth config to Settings**

File: `backend/app/config.py` — add fields:
```python
    # Auth
    jwt_secret_key: str = "change-me-in-production"   # MUST override in .env
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    google_client_id: str = ""                          # For OAuth id_token verification

    # Observability
    sentry_dsn: str = ""
```

- [ ] **Step 3: Create correlation_id middleware**

File: `backend/app/api/middleware/correlation.py`
```python
"""Request correlation ID middleware for tracing."""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
import structlog

logger = structlog.get_logger()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        logger.info("request_started", method=request.method, path=request.url.path)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info("request_completed", status_code=response.status_code)
        return response
```

- [ ] **Step 4: Sync dependencies**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/backend && uv sync
```

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/api/middleware/ backend/uv.lock
git commit -m "feat(auth): add auth dependencies, config, and correlation middleware"
```

---

### Task 2: Auth service (JWT + password + OAuth verification)

**Files:**
- Create: `backend/app/services/auth.py`
- Create: `backend/tests/test_auth_service.py`

- [ ] **Step 1: Write failing tests**

File: `backend/tests/test_auth_service.py`
```python
"""Tests for auth service — JWT and password operations."""

import pytest
from datetime import timedelta
from uuid import uuid4

from app.services.auth import AuthService


class TestJWT:
    def test_create_and_verify_access_token(self):
        svc = AuthService(secret_key="test-secret")
        user_id = uuid4()
        token = svc.create_access_token(user_id=user_id, email="test@example.com")
        payload = svc.verify_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"

    def test_create_and_verify_refresh_token(self):
        svc = AuthService(secret_key="test-secret")
        user_id = uuid4()
        token = svc.create_refresh_token(user_id=user_id)
        payload = svc.verify_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"

    def test_expired_token_raises(self):
        svc = AuthService(secret_key="test-secret")
        token = svc.create_access_token(
            user_id=uuid4(), email="x@x.com",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(ValueError, match="expired"):
            svc.verify_token(token)

    def test_invalid_token_raises(self):
        svc = AuthService(secret_key="test-secret")
        with pytest.raises(ValueError):
            svc.verify_token("not-a-valid-token")

    def test_wrong_secret_raises(self):
        svc1 = AuthService(secret_key="secret-1")
        svc2 = AuthService(secret_key="secret-2")
        token = svc1.create_access_token(user_id=uuid4(), email="x@x.com")
        with pytest.raises(ValueError):
            svc2.verify_token(token)


class TestPassword:
    def test_hash_and_verify(self):
        svc = AuthService(secret_key="test-secret")
        hashed = svc.hash_password("mypassword123")
        assert svc.verify_password("mypassword123", hashed) is True

    def test_wrong_password(self):
        svc = AuthService(secret_key="test-secret")
        hashed = svc.hash_password("correct")
        assert svc.verify_password("wrong", hashed) is False

    def test_hash_is_not_plaintext(self):
        svc = AuthService(secret_key="test-secret")
        hashed = svc.hash_password("mypassword123")
        assert hashed != "mypassword123"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_auth_service.py -v
```

- [ ] **Step 3: Implement AuthService**

File: `backend/app/services/auth.py`
```python
"""Authentication service — JWT tokens, password hashing, OAuth verification."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt


class AuthService:
    """Handles JWT creation/verification and password hashing."""

    def __init__(
        self,
        secret_key: str,
        access_expire_minutes: int = 15,
        refresh_expire_days: int = 7,
    ):
        self._secret = secret_key
        self._access_expire = timedelta(minutes=access_expire_minutes)
        self._refresh_expire = timedelta(days=refresh_expire_days)
        self._algorithm = "HS256"

    # ── JWT ────────────────────────────────────────────

    def create_access_token(
        self, user_id: UUID, email: str,
        expires_delta: timedelta | None = None,
    ) -> str:
        exp = datetime.now(timezone.utc) + (expires_delta or self._access_expire)
        payload = {
            "sub": str(user_id),
            "email": email,
            "type": "access",
            "exp": exp,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(
        self, user_id: UUID,
        expires_delta: timedelta | None = None,
    ) -> str:
        exp = datetime.now(timezone.utc) + (expires_delta or self._refresh_expire)
        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "exp": exp,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT token.

        Returns:
            Decoded payload dict.

        Raises:
            ValueError: If token is invalid or expired.
        """
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e}")

    # ── Password ───────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode(), hashed.encode())

    # ── Google OAuth ───────────────────────────────────

    @staticmethod
    async def verify_google_token(id_token: str, client_id: str) -> dict:
        """Verify a Google OAuth id_token.

        Returns:
            Dict with "sub" (Google user ID), "email", "name", "picture".

        Raises:
            ValueError: If token is invalid.
        """
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        try:
            idinfo = google_id_token.verify_oauth2_token(
                id_token, google_requests.Request(), client_id
            )
            return {
                "sub": idinfo["sub"],
                "email": idinfo["email"],
                "name": idinfo.get("name", ""),
                "picture": idinfo.get("picture", ""),
            }
        except Exception as e:
            raise ValueError(f"Invalid Google token: {e}")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_auth_service.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auth.py backend/tests/test_auth_service.py
git commit -m "feat(auth): add AuthService with JWT, password hashing, Google OAuth"
```

---

### Task 3: DB migration — User auth fields + multi-tenant model configs + usage logs

**Files:**
- Modify: `backend/app/db/models/user.py`
- Create: Alembic migration (auto-generated)

- [ ] **Step 1: Update User ORM model**

File: `backend/app/db/models/user.py` — add columns:
```python
from sqlalchemy import String, Boolean, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

class User(BaseMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    student_profile: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), nullable=False)

    # Auth fields (Phase 2)
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)

    # Relationships
    sources: Mapped[list["Source"]] = relationship("Source", back_populates="creator", lazy="selectin")
```

- [ ] **Step 2: Add user_id to ModelConfig and ModelRouteConfig ORM models**

Read `backend/app/db/models/model_config.py` (or wherever ModelConfig is defined). Add:
```python
user_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("users.id"), nullable=True, index=True
)
```
Same for ModelRouteConfig.

- [ ] **Step 3: Create LlmUsageLog ORM model**

File: `backend/app/db/models/llm_usage_log.py`
```python
"""SQLAlchemy ORM model for LLM usage tracking."""

from sqlalchemy import String, Integer, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class LlmUsageLog(BaseMixin, Base):
    __tablename__ = "llm_usage_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
```

- [ ] **Step 4: Generate and review Alembic migration**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/backend
.venv/bin/alembic revision --autogenerate -m "add auth fields, multi-tenant models, usage logs"
```

Review the generated migration. Ensure it includes:
- users: oauth_provider, oauth_id, avatar_url, hashed_password, is_active + unique index on (oauth_provider, oauth_id)
- model_configs: user_id FK
- model_route_configs: user_id FK
- llm_usage_logs: new table with index on (user_id, created_at)

- [ ] **Step 5: Apply migration**

```bash
.venv/bin/alembic upgrade head
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/ backend/alembic/
git commit -m "feat(db): add auth fields, multi-tenant model configs, LLM usage logs"
```

---

### Task 4: Auth API routes + get_current_user dependency

**Files:**
- Create: `backend/app/api/routes/auth.py`
- Modify: `backend/app/api/deps.py`
- Create: `backend/tests/test_auth_routes.py`

- [ ] **Step 1: Implement get_current_user dependency**

File: `backend/app/api/deps.py` — add:
```python
from fastapi import Header, HTTPException
from app.services.auth import AuthService
from app.db.models.user import User


def _get_auth_service() -> AuthService:
    settings = get_settings()
    return AuthService(
        secret_key=settings.jwt_secret_key,
        access_expire_minutes=settings.jwt_access_expire_minutes,
        refresh_expire_days=settings.jwt_refresh_expire_days,
    )


async def get_current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT from Authorization header, return User."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    auth_service = _get_auth_service()
    try:
        payload = auth_service.verify_token(token)
    except ValueError as e:
        raise HTTPException(401, str(e))

    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")

    from uuid import UUID
    user = await db.get(User, UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")

    return user
```

- [ ] **Step 2: Implement auth routes**

File: `backend/app/api/routes/auth.py`
```python
"""Authentication API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, _get_auth_service
from app.db.models.user import User
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class ExchangeRequest(BaseModel):
    provider: str  # "google", "github", "credentials"
    id_token: str | None = None  # for OAuth
    email: str | None = None      # for credentials
    password: str | None = None   # for credentials


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
    """Register a new user with email + password."""
    # Check email not taken
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
    """Exchange an OAuth token or credentials for JWT tokens."""
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
        # Find or create user
        result = await db.execute(
            select(User).where(User.oauth_provider == "google", User.oauth_id == google_info["sub"])
        )
        user = result.scalar_one_or_none()
        if not user:
            # Check if email exists (link accounts)
            result = await db.execute(select(User).where(User.email == google_info["email"]))
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

    elif request.provider == "github":
        # GitHub OAuth is handled by Auth.js on frontend
        # The exchange endpoint receives the GitHub user info from Auth.js callback
        raise HTTPException(501, "GitHub exchange not yet implemented — handled by Auth.js")

    else:
        raise HTTPException(400, f"Unsupported provider: {request.provider}")

    if not user.is_active:
        raise HTTPException(403, "Account is disabled")

    # Check and claim demo data
    from app.services.auth import maybe_claim_demo_data
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
    """Refresh an access token using a refresh token."""
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
    """Get current authenticated user."""
    from app.api.deps import get_current_user
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        oauth_provider=user.oauth_provider,
    )
```

Add `maybe_claim_demo_data` to `backend/app/services/auth.py`:
```python
async def maybe_claim_demo_data(new_user_id: UUID, db) -> bool:
    """Transfer demo user data to the new user if applicable."""
    from sqlalchemy import select, update as sa_update
    from app.db.models.user import User
    from app.db.models.source import Source
    from app.db.models.conversation import Conversation

    DEMO_ID = UUID("00000000-0000-0000-0000-000000000001")

    if new_user_id == DEMO_ID:
        return False

    demo = await db.get(User, DEMO_ID)
    if not demo:
        return False

    # Transfer sources
    await db.execute(
        sa_update(Source).where(Source.created_by == DEMO_ID).values(created_by=new_user_id)
    )
    # Transfer conversations
    await db.execute(
        sa_update(Conversation).where(Conversation.user_id == DEMO_ID).values(user_id=new_user_id)
    )
    # Delete demo user
    await db.delete(demo)
    await db.flush()
    return True
```

- [ ] **Step 3: Write tests for auth routes**

File: `backend/tests/test_auth_routes.py`
```python
"""Tests for auth API routes."""

import pytest
from httpx import AsyncClient


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        res = await client.post("/api/v1/auth/register", json={
            "email": "new@test.com", "password": "securepass123", "name": "New User",
        })
        assert res.status_code == 201
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "dup@test.com", "password": "pass123",
        })
        res = await client.post("/api/v1/auth/register", json={
            "email": "dup@test.com", "password": "pass456",
        })
        assert res.status_code == 409


class TestExchangeCredentials:
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        # Register first
        await client.post("/api/v1/auth/register", json={
            "email": "login@test.com", "password": "mypassword",
        })
        # Login
        res = await client.post("/api/v1/auth/exchange", json={
            "provider": "credentials", "email": "login@test.com", "password": "mypassword",
        })
        assert res.status_code == 200
        assert "access_token" in res.json()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "wrong@test.com", "password": "correct",
        })
        res = await client.post("/api/v1/auth/exchange", json={
            "provider": "credentials", "email": "wrong@test.com", "password": "incorrect",
        })
        assert res.status_code == 401


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient):
        reg = await client.post("/api/v1/auth/register", json={
            "email": "refresh@test.com", "password": "pass",
        })
        refresh_token = reg.json()["refresh_token"]
        res = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert res.status_code == 200
        assert "access_token" in res.json()

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client: AsyncClient):
        res = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid-token",
        })
        assert res.status_code == 401


class TestMe:
    @pytest.mark.asyncio
    async def test_me_authenticated(self, client: AsyncClient):
        reg = await client.post("/api/v1/auth/register", json={
            "email": "me@test.com", "password": "pass",
        })
        token = reg.json()["access_token"]
        res = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert res.status_code == 200
        assert res.json()["email"] == "me@test.com"

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self, client: AsyncClient):
        res = await client.get("/api/v1/auth/me")
        assert res.status_code == 401
```

- [ ] **Step 4: Register auth router in main.py**

Add to `backend/app/main.py`:
```python
from app.api.routes import auth
app.include_router(auth.router)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_auth_routes.py tests/test_auth_service.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/auth.py backend/app/api/deps.py backend/app/services/auth.py backend/app/main.py backend/tests/test_auth_routes.py
git commit -m "feat(auth): add auth routes (register, exchange, refresh, me)"
```

---

### Task 5: API versioning — migrate all routes to /api/v1/

**Files:**
- Modify: `backend/app/main.py`
- Modify: All route files (prefix changes)

- [ ] **Step 1: Update all route prefixes**

Change each router's prefix:
- `sources.py`: `/api/sources` → `/api/v1/sources`
- `courses.py`: `/api/courses` → `/api/v1/courses`
- `models.py`: `/api/models` → `/api/v1/models`
- `model_routes.py`: `/api/model-routes` → `/api/v1/model-routes`
- `tasks.py`: `/api/tasks` → `/api/v1/tasks`
- `health.py`: keep `/health` (no versioning for health check)
- `chat.py`: `/api/chat` → `/api/v1/chat` (and `/api/conversations` → `/api/v1/conversations`)

- [ ] **Step 2: Update smoke tests**

Update all URLs in `tests/test_smoke.py` from `/api/` to `/api/v1/`.

- [ ] **Step 3: Run all tests**

```bash
.venv/bin/python -m pytest -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/ backend/tests/
git commit -m "refactor: migrate all API routes to /api/v1/ prefix"
```

---

### Task 6: User scoping — add auth to all data routes

**Files:**
- Modify: `backend/app/api/routes/sources.py`
- Modify: `backend/app/api/routes/courses.py`
- Modify: `backend/app/api/routes/chat.py`
- Modify: `backend/app/api/routes/models.py`
- Modify: `backend/app/api/routes/model_routes.py`
- Create: `backend/tests/test_user_scoping.py`

- [ ] **Step 1: Add get_current_user to sources.py**

Every route that accesses data gets `user: Annotated[User, Depends(get_current_user)]`:

```python
# create_source: set source.created_by = user.id
# list_sources: filter WHERE created_by = user.id
# get_source: filter WHERE created_by = user.id, return 404 if not found
```

- [ ] **Step 2: Add get_current_user to courses.py**

```python
# generate_course: set course.created_by = user.id
# list_courses: filter WHERE created_by = user.id
# get_course: filter WHERE created_by = user.id
```

- [ ] **Step 3: Update chat.py — remove DEMO_USER_ID**

Remove `DEMO_USER_ID` constant. Replace all `user_id = DEMO_USER_ID` with `user_id = user.id` from `get_current_user`. The chat endpoint creates its own session, so pass `user_id` as parameter.

For conversations list and messages: filter by `user.id`.

- [ ] **Step 4: Add user scoping to models.py**

```python
# list_models: WHERE user_id = user.id OR user_id IS NULL
# create_model: set user_id = user.id
# update/delete: WHERE name = ? AND user_id = user.id
# test: WHERE name = ? AND (user_id = user.id OR user_id IS NULL)
```

- [ ] **Step 5: Write user scoping tests**

File: `backend/tests/test_user_scoping.py`
```python
"""Tests for user-scoped data isolation."""

import pytest
from httpx import AsyncClient
from app.services.auth import AuthService


async def _register_and_get_token(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "testpass123",
    })
    return res.json()["access_token"]


class TestSourceIsolation:
    @pytest.mark.asyncio
    async def test_user_sees_only_own_sources(self, client: AsyncClient):
        token_a = await _register_and_get_token(client, "a@test.com")
        token_b = await _register_and_get_token(client, "b@test.com")

        # User A creates a source (mock celery)
        from unittest.mock import patch, MagicMock
        with patch("app.api.routes.sources.ingest_source") as mock:
            mock.delay.return_value = MagicMock(id="task-1")
            await client.post("/api/v1/sources", data={"url": "https://bilibili.com/video/BV1test"},
                              headers={"Authorization": f"Bearer {token_a}"})

        # User B should see 0 sources
        res = await client.get("/api/v1/sources", headers={"Authorization": f"Bearer {token_b}"})
        assert res.json()["total"] == 0

        # User A should see 1 source
        res = await client.get("/api/v1/sources", headers={"Authorization": f"Bearer {token_a}"})
        assert res.json()["total"] == 1


class TestUnauthenticatedAccess:
    @pytest.mark.asyncio
    async def test_sources_requires_auth(self, client: AsyncClient):
        res = await client.get("/api/v1/sources")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_courses_requires_auth(self, client: AsyncClient):
        res = await client.get("/api/v1/courses")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_requires_auth(self, client: AsyncClient):
        res = await client.post("/api/v1/chat", json={"message": "hi"})
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_conversations_requires_auth(self, client: AsyncClient):
        res = await client.get("/api/v1/conversations")
        assert res.status_code == 401
```

- [ ] **Step 6: Run all tests**

```bash
.venv/bin/python -m pytest -v --tb=short
```

Note: Some existing smoke tests may need updating to include auth tokens. Create a helper fixture:
```python
@pytest_asyncio.fixture
async def auth_token(client: AsyncClient) -> str:
    """Register a test user and return access token."""
    res = await client.post("/api/v1/auth/register", json={
        "email": "testuser@smoke.com", "password": "smoketest123",
    })
    return res.json()["access_token"]
```

Update smoke tests to use this fixture and pass `headers={"Authorization": f"Bearer {token}"}`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/ backend/tests/
git commit -m "feat(auth): add user scoping to all data routes, remove DEMO_USER_ID"
```

---

### Task 7: Rate limiting middleware

**Files:**
- Create: `backend/app/api/middleware/rate_limit.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Implement rate limiter**

File: `backend/app/api/middleware/rate_limit.py`
```python
"""Redis-based rate limiting middleware."""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

import redis.asyncio as aioredis

from app.config import get_settings


# Rate limit rules: (prefix, max_requests, window_seconds)
RATE_LIMITS = [
    ("/api/v1/auth/", 10, 60),           # 10 req/min per IP
    ("/api/v1/diagnostic/", 5, 60),       # 5 req/min per user
    ("/api/v1/exercises/generate", 5, 60),
    ("/api/v1/translate", 3, 60),
]
DEFAULT_LIMIT = (60, 60)  # 60 req/min


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # Find matching rule
        max_req, window = DEFAULT_LIMIT
        for prefix, limit, win in RATE_LIMITS:
            if path.startswith(prefix):
                max_req, window = limit, win
                break

        # For auth routes, key by IP; for others, key by token sub if available
        if path.startswith("/api/v1/auth/"):
            key = f"ratelimit:{client_ip}:{path.split('/')[3]}"
        else:
            # Extract user from token if present (lightweight, no DB)
            auth_header = request.headers.get("authorization", "")
            key = f"ratelimit:{client_ip}:{path}"
            if auth_header.startswith("Bearer "):
                import jwt
                try:
                    payload = jwt.decode(
                        auth_header[7:],
                        options={"verify_signature": False, "verify_exp": False},
                    )
                    key = f"ratelimit:{payload.get('sub', client_ip)}:{path}"
                except Exception:
                    pass

        # Check Redis
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url)
        try:
            current = await r.incr(key)
            if current == 1:
                await r.expire(key, window)
            if current > max_req:
                raise HTTPException(429, "Rate limit exceeded")
        finally:
            await r.aclose()

        return await call_next(request)
```

- [ ] **Step 2: Add middleware to main.py**

```python
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.correlation import CorrelationIdMiddleware

# Add BEFORE CORS (order matters — last added = first executed)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/middleware/ backend/app/main.py
git commit -m "feat: add rate limiting and correlation ID middleware"
```

---

### Task 8: Cost guard service

**Files:**
- Create: `backend/app/services/cost_guard.py`
- Test: `backend/tests/test_cost_guard.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for LLM cost guard."""
import pytest
from uuid import uuid4
from app.services.cost_guard import CostGuard


class TestCostGuard:
    @pytest.mark.asyncio
    async def test_log_usage(self, db_session):
        guard = CostGuard(db_session)
        await guard.log_usage(
            user_id=uuid4(), task_type="diagnostic",
            model_name="claude-sonnet", tokens_in=500, tokens_out=200,
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_check_budget_within_limit(self, db_session):
        guard = CostGuard(db_session)
        user_id = uuid4()
        allowed = await guard.check_budget(user_id, "diagnostic")
        assert allowed is True
```

- [ ] **Step 2: Implement CostGuard**

File: `backend/app/services/cost_guard.py`
```python
"""LLM usage tracking and budget enforcement."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.llm_usage_log import LlmUsageLog


# Default daily token limits per task type
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
        """Log an LLM usage event."""
        # Rough cost estimate (varies by model, this is approximate)
        cost = (tokens_in * 0.000003) + (tokens_out * 0.000015)
        log = LlmUsageLog(
            user_id=user_id, task_type=task_type,
            model_name=model_name, tokens_in=tokens_in,
            tokens_out=tokens_out, estimated_cost_usd=cost,
        )
        self._db.add(log)
        await self._db.flush()

    async def check_budget(self, user_id: UUID, task_type: str) -> bool:
        """Check if user is within daily budget for this task type."""
        limit = DEFAULT_LIMITS.get(task_type, 100_000)
        since = datetime.now(timezone.utc) - timedelta(days=1)

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
```

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python -m pytest tests/test_cost_guard.py -v
git add backend/app/services/cost_guard.py backend/tests/test_cost_guard.py
git commit -m "feat: add CostGuard service for LLM usage tracking and budgets"
```

---

### Task 9: Frontend — Auth.js setup + login page

**Files:**
- Create: `frontend/src/lib/auth.ts`
- Create: `frontend/src/app/api/auth/[...nextauth]/route.ts`
- Create: `frontend/src/app/login/page.tsx`
- Create: `frontend/src/middleware.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Install next-auth**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/frontend
npm install next-auth@beta
```

Note: Read `node_modules/next/dist/docs/` for any Next.js 16 specific guidance before proceeding.

- [ ] **Step 2: Create Auth.js config**

File: `frontend/src/lib/auth.ts`
```typescript
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import GitHub from "next-auth/providers/github";
import Credentials from "next-auth/providers/credentials";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    }),
    GitHub({
      clientId: process.env.GITHUB_CLIENT_ID,
      clientSecret: process.env.GITHUB_CLIENT_SECRET,
    }),
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/exchange`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: "credentials",
            email: credentials.email,
            password: credentials.password,
          }),
        });
        if (!res.ok) return null;
        const tokens = await res.json();
        return {
          id: "credentials-user",
          email: credentials.email as string,
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      // On first sign-in, exchange OAuth token for backend JWT
      if (account && account.provider !== "credentials") {
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/exchange`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: account.provider,
            id_token: account.id_token,
          }),
        });
        if (res.ok) {
          const tokens = await res.json();
          token.accessToken = tokens.access_token;
          token.refreshToken = tokens.refresh_token;
        }
      }
      if (user?.accessToken) {
        token.accessToken = user.accessToken;
        token.refreshToken = user.refreshToken;
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
```

- [ ] **Step 3: Create Auth.js route handler**

File: `frontend/src/app/api/auth/[...nextauth]/route.ts`
```typescript
import { handlers } from "@/lib/auth";
export const { GET, POST } = handlers;
```

- [ ] **Step 4: Create BFF proxy route**

File: `frontend/src/app/api/v1/[...proxy]/route.ts`
```typescript
import { auth } from "@/lib/auth";
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function proxyRequest(req: NextRequest) {
  const session = await auth();
  const path = req.nextUrl.pathname; // e.g. /api/v1/sources
  const url = `${BACKEND_URL}${path}${req.nextUrl.search}`;

  const headers: HeadersInit = {};
  // Forward content-type
  const ct = req.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;
  // Inject JWT
  if (session?.accessToken) {
    headers["Authorization"] = `Bearer ${session.accessToken}`;
  }

  const body = req.method !== "GET" && req.method !== "HEAD"
    ? await req.arrayBuffer()
    : undefined;

  const res = await fetch(url, {
    method: req.method,
    headers,
    body,
  });

  // Stream the response back
  return new NextResponse(res.body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") || "application/json",
    },
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
```

- [ ] **Step 5: Create login page**

File: `frontend/src/app/login/page.tsx`
```tsx
"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (isRegister) {
      // Register first, then sign in
      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "注册失败");
        setLoading(false);
        return;
      }
    }

    const result = await signIn("credentials", {
      email, password, redirect: false,
    });
    setLoading(false);

    if (result?.error) {
      setError("邮箱或密码错误");
    } else {
      router.push("/");
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">LearnMentor</h1>
          <p className="text-sm text-gray-500 mt-1">AI 驱动的自适应学习系统</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          {/* OAuth buttons */}
          <button onClick={() => signIn("google", { callbackUrl: "/" })}
            className="w-full flex items-center justify-center gap-2 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50">
            Google 登录
          </button>
          <button onClick={() => signIn("github", { callbackUrl: "/" })}
            className="w-full flex items-center justify-center gap-2 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50">
            GitHub 登录
          </button>

          <div className="relative my-4">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200" /></div>
            <div className="relative flex justify-center text-xs"><span className="bg-white px-2 text-gray-400">或</span></div>
          </div>

          {/* Email form */}
          <form onSubmit={handleCredentials} className="space-y-3">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="邮箱" required
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="密码" required minLength={6}
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {error && <p className="text-xs text-red-500">{error}</p>}
            <button type="submit" disabled={loading}
              className="w-full py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {loading ? "处理中..." : isRegister ? "注册" : "登录"}
            </button>
          </form>

          <button onClick={() => { setIsRegister(!isRegister); setError(""); }}
            className="w-full text-xs text-blue-600 hover:text-blue-700">
            {isRegister ? "已有账号？登录" : "没有账号？注册"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create auth middleware**

File: `frontend/src/middleware.ts`
```typescript
export { auth as middleware } from "@/lib/auth";

export const config = {
  // Protect all routes except login, api/auth, and static files
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 7: Update api.ts — change API_BASE**

File: `frontend/src/lib/api.ts` — change line 3:
```typescript
const API_BASE = "/api/v1";
```

- [ ] **Step 8: Build and verify**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/frontend && npm run build
```

- [ ] **Step 9: Commit**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor
git add frontend/
git commit -m "feat(frontend): add Auth.js BFF auth, login page, API proxy"
```

---

### Task 10: Settings UI enhancement — account section + model creation form

**Files:**
- Modify: `frontend/src/app/settings/page.tsx`
- Modify: `frontend/src/lib/api.ts` (add createModel API)

- [ ] **Step 1: Ensure createModel exists in api.ts**

The `createModel` function should already exist in `api.ts`. Verify it matches:
```typescript
export async function createModel(data: {
  name: string; provider_type: string; model_id: string;
  api_key?: string; base_url?: string;
}): Promise<ModelConfigResponse> { ... }
```

Also add `updateModelRoutes`:
```typescript
export async function updateModelRoutes(routes: { task_type: string; model_name: string }[]): Promise<ModelRouteResponse[]> {
  const res = await fetch(`${API_BASE}/model-routes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(routes),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 2: Rewrite settings page with account section + model form + route editor**

The settings page should have three sections:
1. **账户** — avatar, name, email, OAuth connections, logout
2. **模型配置** — existing list + "添加模型" modal form
3. **模型路由** — dropdown per task_type selecting from configured models

Use `useSession` from `next-auth/react` for account info. Use `signOut` for logout.

The model creation form is a modal/dialog with: provider_type dropdown, model_id input, api_key input (masked), base_url input, test button, save button.

- [ ] **Step 3: Build and verify**

```bash
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/settings/page.tsx frontend/src/lib/api.ts
git commit -m "feat(frontend): enhance settings with account section and model creation form"
```

---

### Task 11: Update existing smoke tests + final verification

**Files:**
- Modify: `backend/tests/test_smoke.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Add auth_token fixture to conftest.py**

```python
@pytest_asyncio.fixture
async def auth_token(client, db_session):
    """Register a test user and return access token."""
    # Create user directly in DB to avoid dependency on auth routes
    from app.services.auth import AuthService
    svc = AuthService(secret_key="test-secret-key")
    user = User(
        id=uuid.uuid4(), email="smoke@test.com", name="Smoke Tester",
        hashed_password=svc.hash_password("testpass"),
    )
    db_session.add(user)
    await db_session.flush()
    token = svc.create_access_token(user.id, user.email)
    return token
```

Override the JWT secret in test config so `get_current_user` can verify:
```python
# In conftest.py, set env before app import
import os
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
```

- [ ] **Step 2: Update all smoke tests to use auth headers**

Every `client.post("/api/v1/sources", ...)` call needs `headers={"Authorization": f"Bearer {auth_token}"}`.

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/backend
.venv/bin/python -m pytest -v
```

- [ ] **Step 4: Run frontend build + tests**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/learnmentor/frontend
npm run build && npm test
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/ frontend/
git commit -m "test: update smoke tests for auth, verify full suite passes"
```
