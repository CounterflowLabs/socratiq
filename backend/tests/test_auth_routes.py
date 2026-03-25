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
        assert data["token_type"] == "bearer"

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
        await client.post("/api/v1/auth/register", json={
            "email": "login@test.com", "password": "mypassword",
        })
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

    @pytest.mark.asyncio
    async def test_login_nonexistent_email(self, client: AsyncClient):
        res = await client.post("/api/v1/auth/exchange", json={
            "provider": "credentials", "email": "noone@test.com", "password": "pass",
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

    @pytest.mark.asyncio
    async def test_me_with_invalid_token(self, client: AsyncClient):
        res = await client.get("/api/v1/auth/me", headers={
            "Authorization": "Bearer invalid-token-here",
        })
        assert res.status_code == 401
