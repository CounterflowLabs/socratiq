"""Setup API regression tests."""

from cryptography.fernet import Fernet
import pytest

from app.db.models.whisper_config import WhisperConfig
from app.services.llm.encryption import encrypt_api_key


@pytest.mark.asyncio
async def test_get_whisper_config_handles_unreadable_encrypted_key(
    client,
    db_session,
    demo_user,
):
    wrong_key = Fernet.generate_key().decode()
    db_session.add(
        WhisperConfig(
            user_id=demo_user.id,
            mode="api",
            api_base_url="https://api.groq.com/openai/v1",
            api_model="whisper-large-v3",
            api_key_encrypted=encrypt_api_key("gsk-test-whisper-key", wrong_key),
            local_model="base",
        )
    )
    await db_session.flush()

    res = await client.get("/api/v1/setup/whisper")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "api"
    assert data["api_base_url"] == "https://api.groq.com/openai/v1"
    assert data["api_model"] == "whisper-large-v3"
    assert data["local_model"] == "base"
    assert "gsk-test-whisper-key" not in str(data.get("api_key_masked"))
