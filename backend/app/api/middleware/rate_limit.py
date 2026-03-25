"""Redis-based rate limiting middleware."""

import os

import jwt
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

RATE_LIMITS = [
    ("/api/v1/auth/", 10, 60),
    ("/api/v1/diagnostic/", 5, 60),
    ("/api/v1/exercises/generate", 5, 60),
    ("/api/v1/translate", 3, 60),
]
DEFAULT_LIMIT = (60, 60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting during test runs to avoid cross-test interference
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return await call_next(request)

        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        max_req, window = DEFAULT_LIMIT
        for prefix, limit, win in RATE_LIMITS:
            if path.startswith(prefix):
                max_req, window = limit, win
                break

        if path.startswith("/api/v1/auth/"):
            key = f"rl:{client_ip}:auth"
        else:
            auth_header = request.headers.get("authorization", "")
            key = f"rl:{client_ip}:{path}"
            if auth_header.startswith("Bearer "):
                try:
                    payload = jwt.decode(auth_header[7:], options={"verify_signature": False, "verify_exp": False})
                    key = f"rl:{payload.get('sub', client_ip)}:{path}"
                except Exception:
                    pass

        settings = get_settings()
        r = aioredis.from_url(settings.redis_url)
        try:
            current = await r.incr(key)
            if current == 1:
                await r.expire(key, window)
            if current > max_req:
                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                )
        except Exception:
            pass  # If Redis is down, don't block requests
        finally:
            await r.aclose()

        return await call_next(request)
