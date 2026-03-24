"""API key encryption utilities using Fernet symmetric encryption."""

from cryptography.fernet import Fernet, InvalidToken


def encrypt_api_key(key: str, fernet_key: str) -> str:
    """Encrypt an API key for storage."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.encrypt(key.encode()).decode()


def decrypt_api_key(encrypted: str, fernet_key: str) -> str:
    """Decrypt a stored API key."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.decrypt(encrypted.encode()).decode()


def mask_api_key(key: str) -> str:
    """Mask an API key for display, showing only last 4 characters."""
    if len(key) <= 4:
        return "****"
    return f"{'*' * (len(key) - 4)}{key[-4:]}"
