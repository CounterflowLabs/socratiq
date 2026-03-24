"""Tests for API key encryption utilities."""

import pytest
from cryptography.fernet import Fernet

from app.services.llm.encryption import decrypt_api_key, encrypt_api_key, mask_api_key


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


class TestEncryptDecrypt:
    def test_roundtrip(self, fernet_key: str) -> None:
        original = "sk-ant-api03-test-key-12345"
        encrypted = encrypt_api_key(original, fernet_key)
        assert encrypted != original
        decrypted = decrypt_api_key(encrypted, fernet_key)
        assert decrypted == original

    def test_different_keys_produce_different_ciphertext(self) -> None:
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        original = "sk-test-key"
        enc1 = encrypt_api_key(original, key1)
        enc2 = encrypt_api_key(original, key2)
        assert enc1 != enc2

    def test_wrong_key_fails(self) -> None:
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        encrypted = encrypt_api_key("secret", key1)
        with pytest.raises(Exception):
            decrypt_api_key(encrypted, key2)


class TestMaskApiKey:
    def test_normal_key(self) -> None:
        assert mask_api_key("sk-ant-api03-test-key-12345") == "***********************2345"

    def test_short_key(self) -> None:
        assert mask_api_key("abc") == "****"

    def test_exactly_four(self) -> None:
        assert mask_api_key("abcd") == "****"

    def test_five_chars(self) -> None:
        assert mask_api_key("abcde") == "*bcde"
