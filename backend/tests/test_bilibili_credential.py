"""Tests for the shared Bilibili credential helpers."""

import pytest

from app.config import get_settings
from app.db.models.bilibili_credential import BilibiliCredential
from app.services.bilibili_credential import (
    has_bilibili_credential,
    load_bilibili_credential,
)
from app.services.llm.encryption import encrypt_api_key


@pytest.mark.asyncio
async def test_has_bilibili_credential_true_when_db_row_present(
    db_session, demo_user, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "")

    db_session.add(
        BilibiliCredential(
            user_id=demo_user.id,
            sessdata_encrypted=encrypt_api_key(
                "fake-sessdata", settings.llm_encryption_key
            ),
        )
    )
    await db_session.flush()

    assert await has_bilibili_credential(db_session) is True


@pytest.mark.asyncio
async def test_has_bilibili_credential_falls_back_to_env(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "env-sessdata")

    assert await has_bilibili_credential(db_session) is True


@pytest.mark.asyncio
async def test_has_bilibili_credential_returns_false_when_nothing_configured(
    db_session, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "")

    assert await has_bilibili_credential(db_session) is False


@pytest.mark.asyncio
async def test_load_bilibili_credential_uses_env_when_no_db(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "env-sessdata")
    monkeypatch.setattr(settings, "bilibili_bili_jct", "env-jct")
    monkeypatch.setattr(settings, "bilibili_buvid3", "env-buvid3")

    credential = await load_bilibili_credential(db_session)

    assert credential is not None
    assert credential.sessdata == "env-sessdata"
    assert credential.bili_jct == "env-jct"


@pytest.mark.asyncio
async def test_load_bilibili_credential_returns_none_when_unconfigured(
    db_session, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "bilibili_sessdata", "")

    assert await load_bilibili_credential(db_session) is None
