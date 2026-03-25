"""Request correlation ID middleware for tracing."""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
