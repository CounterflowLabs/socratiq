"""E2E smoke tests for core API endpoints.

These tests verify API contracts by hitting endpoints via ASGI transport.
Requires running PostgreSQL and Redis (use docker compose up -d db redis).
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCoreEndpoints:
    """Verify core API endpoints respond with correct status codes."""

    @pytest.mark.asyncio
    async def test_health(self, client):
        """GET /health returns 200."""
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_setup_status(self, client):
        """GET /api/v1/setup/status returns 200."""
        resp = await client.get("/api/v1/setup/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_courses(self, client):
        """GET /api/v1/courses returns 200."""
        resp = await client.get("/api/v1/courses")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """GET /api/v1/models returns 200."""
        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_reviews_due(self, client):
        """GET /api/v1/reviews/due returns 200."""
        resp = await client.get("/api/v1/reviews/due")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_review_stats(self, client):
        """GET /api/v1/reviews/stats returns 200."""
        resp = await client.get("/api/v1/reviews/stats")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_conversations(self, client):
        """GET /api/v1/conversations returns 200."""
        resp = await client.get("/api/v1/conversations")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_sources(self, client):
        """GET /api/v1/sources returns 200."""
        resp = await client.get("/api/v1/sources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_model_routes(self, client):
        """GET /api/v1/model-routes returns 200."""
        resp = await client.get("/api/v1/model-routes")
        assert resp.status_code == 200
