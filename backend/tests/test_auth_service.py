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
