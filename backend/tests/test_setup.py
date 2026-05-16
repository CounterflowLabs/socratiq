"""Setup API regression tests."""

from cryptography.fernet import Fernet
import pytest

from app.config import get_settings
from app.api.routes.setup import _split_ollama_models
from app.db.models.bilibili_credential import BilibiliCredential
from app.db.models.whisper_config import WhisperConfig
from app.services.llm.encryption import encrypt_api_key


def test_split_ollama_models_keeps_embedding_models_out_of_chat_list():
    chat_models, embedding_models = _split_ollama_models(
        ["nomic-embed-text:latest", "qwen3.6:latest", "bge-m3:latest"]
    )

    assert chat_models == ["qwen3.6:latest"]
    assert embedding_models == ["nomic-embed-text:latest", "bge-m3:latest"]


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


@pytest.mark.asyncio
async def test_bilibili_status_returns_logged_out_when_unconfigured(
    client, demo_user, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "")

    res = await client.get("/api/v1/setup/bilibili/status")

    assert res.status_code == 200
    body = res.json()
    assert body["logged_in"] is False
    assert body["source"] is None


@pytest.mark.asyncio
async def test_bilibili_status_reports_db_credential(
    client, db_session, demo_user, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "")

    db_session.add(
        BilibiliCredential(
            user_id=demo_user.id,
            sessdata_encrypted=encrypt_api_key(
                "fake-sessdata", settings.llm_encryption_key
            ),
            dedeuserid="123456",
        )
    )
    await db_session.flush()

    res = await client.get("/api/v1/setup/bilibili/status")

    assert res.status_code == 200
    body = res.json()
    assert body["logged_in"] is True
    assert body["source"] == "db"
    assert body["dedeuserid"] == "123456"


@pytest.mark.asyncio
async def test_bilibili_status_reports_env_fallback(client, demo_user, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "env-sessdata")

    res = await client.get("/api/v1/setup/bilibili/status")

    assert res.status_code == 200
    body = res.json()
    assert body["logged_in"] is True
    assert body["source"] == "env"
    assert body["dedeuserid"] is None
