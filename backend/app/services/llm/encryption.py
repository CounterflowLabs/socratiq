"""API key encryption utilities using Fernet symmetric encryption."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _build_fernet(fernet_key: str | bytes) -> Fernet:
    """Create a Fernet instance from either a real Fernet key or a plain passphrase.

    Local dev `.env` files in this project historically used a human-readable
    string instead of a urlsafe-base64 Fernet key. To preserve compatibility, we
    deterministically derive a valid Fernet key from that passphrase.
    """
    raw_key = fernet_key.encode() if isinstance(fernet_key, str) else fernet_key
    try:
        return Fernet(raw_key)
    except ValueError:
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
        return Fernet(derived_key)


def encrypt_api_key(key: str, fernet_key: str) -> str:
    """Encrypt an API key for storage."""
    f = _build_fernet(fernet_key)
    return f.encrypt(key.encode()).decode()


def decrypt_api_key(encrypted: str, fernet_key: str) -> str:
    """Decrypt a stored API key."""
    f = _build_fernet(fernet_key)
    return f.decrypt(encrypted.encode()).decode()


def decrypt_api_key_or_none(encrypted: str | None, fernet_key: str) -> str | None:
    """Best-effort decrypt for stored secrets.

    Returns ``None`` when the stored ciphertext cannot be read with the current
    encryption key so callers can safely fall back to environment defaults.
    """
    if not encrypted:
        return None

    try:
        return decrypt_api_key(encrypted, fernet_key)
    except (InvalidToken, ValueError, TypeError):
        return None


def mask_api_key(key: str) -> str:
    """Mask an API key for display, showing only last 4 characters."""
    if len(key) <= 4:
        return "****"
    return f"{'*' * (len(key) - 4)}{key[-4:]}"
