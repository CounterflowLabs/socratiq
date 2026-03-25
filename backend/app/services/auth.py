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

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode(), hashed.encode())

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
