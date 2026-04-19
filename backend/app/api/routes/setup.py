"""API routes for first-time setup / onboarding."""

import httpx
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.bilibili_credential import BilibiliCredential
from app.db.models.model_config import ModelConfig
from app.db.models.user import User
from app.db.models.whisper_config import WhisperConfig
from app.models.model_schemas import WhisperConfigResponse, WhisperConfigUpdate
from app.services.llm.encryption import decrypt_api_key, encrypt_api_key
from app.services.llm.codex_auth import (
    codex_login_manager,
    get_codex_login_status,
    list_codex_models,
)

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])
_bilibili_qr_sessions: dict[str, object] = {}


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Check if the system is configured."""
    result = await db.execute(select(ModelConfig).limit(1))
    has_models = result.scalar_one_or_none() is not None

    # Try to detect Ollama
    ollama_available = False
    ollama_models = []
    ollama_base_url = None
    for base_url in ["http://localhost:11434", "http://host.docker.internal:11434"]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    ollama_available = True
                    ollama_base_url = f"{base_url}/v1"
                    data = resp.json()
                    ollama_models = [m["name"] for m in data.get("models", [])]
                    break
        except Exception:
            continue

    codex_status = await get_codex_login_status()
    codex_models: list[dict[str, str]] = []
    codex_error = None
    if codex_status["logged_in"]:
        try:
            codex_models = await list_codex_models()
        except Exception as exc:
            codex_error = str(exc)

    return {
        "has_models": has_models,
        "ollama_available": ollama_available,
        "ollama_models": ollama_models,
        "ollama_base_url": ollama_base_url,
        "codex_available": codex_status["available"],
        "codex_logged_in": codex_status["logged_in"],
        "codex_auth_mode": codex_status["auth_mode"],
        "codex_status_message": codex_status["message"],
        "codex_models": codex_models,
        "codex_error": codex_error,
    }


@router.post("/codex/login/start")
async def start_codex_login():
    """Start or reuse an official ChatGPT device-auth flow for Codex CLI."""
    try:
        return await codex_login_manager.start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/codex/login/{session_id}")
async def get_codex_login_session(session_id: str):
    """Return the latest state for a device-auth session."""
    session = codex_login_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Codex 登录会话不存在。")
    return session.snapshot()


@router.get("/whisper", response_model=WhisperConfigResponse)
async def get_whisper_config(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
):
    """Return Whisper ASR config for the current local user."""
    settings = get_settings()

    result = await db.execute(
        select(WhisperConfig).where(WhisperConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        return WhisperConfigResponse(
            mode=settings.whisper_mode,
            api_base_url=settings.whisper_api_base_url,
            api_model=settings.whisper_api_model,
            api_key_masked=_mask_key(settings.whisper_api_key),
            local_model=settings.whisper_model,
        )

    return WhisperConfigResponse(
        mode=config.mode,
        api_base_url=config.api_base_url,
        api_model=config.api_model,
        api_key_masked=(
            _mask_key(decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key))
            if config.api_key_encrypted
            else _mask_key(settings.whisper_api_key)
        ),
        local_model=config.local_model,
    )


@router.put("/whisper", response_model=WhisperConfigResponse)
async def update_whisper_config(
    data: WhisperConfigUpdate,
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
):
    """Persist Whisper ASR config for the current local user."""
    settings = get_settings()

    result = await db.execute(
        select(WhisperConfig).where(WhisperConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = WhisperConfig(user_id=user.id)
        db.add(config)

    if data.mode is not None:
        config.mode = data.mode
    if data.api_base_url is not None:
        config.api_base_url = data.api_base_url
    if data.api_model is not None:
        config.api_model = data.api_model
    if data.api_key is not None:
        config.api_key_encrypted = (
            encrypt_api_key(data.api_key, settings.llm_encryption_key)
            if data.api_key
            else None
        )
    if data.local_model is not None:
        config.local_model = data.local_model

    await db.flush()

    return WhisperConfigResponse(
        mode=config.mode,
        api_base_url=config.api_base_url,
        api_model=config.api_model,
        api_key_masked=(
            _mask_key(decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key))
            if config.api_key_encrypted
            else _mask_key(settings.whisper_api_key)
        ),
        local_model=config.local_model,
    )


@router.get("/bilibili/status")
async def get_bilibili_status(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
):
    """Return whether a Bilibili account is already linked for the local user."""
    result = await db.execute(
        select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
    )
    credential = result.scalar_one_or_none()
    if credential and credential.sessdata_encrypted:
        return {"logged_in": True, "dedeuserid": credential.dedeuserid}
    return {"logged_in": False}


@router.post("/bilibili/qrcode")
async def generate_bilibili_qrcode(
    user: Annotated[User, Depends(get_local_user)],
):
    """Generate a Bilibili QR code for browser-based login."""
    import base64

    from bilibili_api.login_v2 import QrCodeLogin

    qr = QrCodeLogin()
    await qr.generate_qrcode()
    _bilibili_qr_sessions[str(user.id)] = qr

    return {
        "status": "generated",
        "qrcode_base64": base64.b64encode(qr.get_qrcode_picture().content).decode(),
    }


@router.get("/bilibili/qrcode/status")
async def check_bilibili_qrcode(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
):
    """Check scan status and persist credential when login finishes."""
    from bilibili_api.login_v2 import QrCodeLoginEvents

    qr = _bilibili_qr_sessions.get(str(user.id))
    if not qr:
        return {"status": "expired"}

    state = await qr.check_state()
    if state == QrCodeLoginEvents.SCAN:
        return {"status": "waiting"}
    if state == QrCodeLoginEvents.CONF:
        return {"status": "scanned"}
    if state == QrCodeLoginEvents.TIMEOUT:
        _bilibili_qr_sessions.pop(str(user.id), None)
        return {"status": "expired"}
    if state != QrCodeLoginEvents.DONE:
        return {"status": "unknown"}

    credential = qr.get_credential()
    settings = get_settings()

    result = await db.execute(
        select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
    )
    stored = result.scalar_one_or_none()
    if not stored:
        stored = BilibiliCredential(user_id=user.id)
        db.add(stored)

    stored.sessdata_encrypted = encrypt_api_key(
        credential.sessdata,
        settings.llm_encryption_key,
    )
    stored.bili_jct_encrypted = (
        encrypt_api_key(credential.bili_jct, settings.llm_encryption_key)
        if credential.bili_jct
        else None
    )
    stored.dedeuserid = credential.dedeuserid

    await db.flush()
    _bilibili_qr_sessions.pop(str(user.id), None)

    return {"status": "done", "dedeuserid": credential.dedeuserid}


@router.delete("/bilibili")
async def logout_bilibili(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
):
    """Remove the linked Bilibili credential for the current local user."""
    result = await db.execute(
        select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
    )
    credential = result.scalar_one_or_none()
    if credential:
        await db.delete(credential)
        await db.flush()
    _bilibili_qr_sessions.pop(str(user.id), None)
    return {"status": "logged_out"}


def _mask_key(key: str | None) -> str | None:
    """Mask an API key for display."""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]
