"""Tests verifying user-scoped data isolation."""
import pytest
from uuid import uuid4
from unittest.mock import patch, MagicMock
from httpx import AsyncClient


async def _register(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "testpass123",
    })
    return res.json()["access_token"]


class TestSourceIsolation:
    @pytest.mark.asyncio
    async def test_users_see_only_own_sources(self, client: AsyncClient):
        token_a = await _register(client, f"a-{uuid4().hex[:6]}@test.com")
        token_b = await _register(client, f"b-{uuid4().hex[:6]}@test.com")

        with patch("app.api.routes.sources.ingest_source") as mock:
            mock.delay.return_value = MagicMock(id="task-1")
            await client.post("/api/v1/sources",
                data={"url": "https://bilibili.com/video/BV1test"},
                headers={"Authorization": f"Bearer {token_a}"})

        res_b = await client.get("/api/v1/sources", headers={"Authorization": f"Bearer {token_b}"})
        assert res_b.json()["total"] == 0

        res_a = await client.get("/api/v1/sources", headers={"Authorization": f"Bearer {token_a}"})
        assert res_a.json()["total"] >= 1


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
