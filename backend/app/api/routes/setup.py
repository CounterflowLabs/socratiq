"""API routes for first-time setup / onboarding."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.model_config import ModelConfig
from app.db.models.user import User
from app.db.models.whisper_config import WhisperConfig
from app.models.model_schemas import WhisperConfigResponse, WhisperConfigUpdate
from app.services.llm.encryption import encrypt_api_key, decrypt_api_key, mask_api_key

router = APIRouter(prefix="/api/v1", tags=["setup"])

# In-memory storage for active Bilibili QR login sessions
_bilibili_qr_sessions: dict[str, object] = {}


@router.get("/setup/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Check if the system is configured."""
    result = await db.execute(select(ModelConfig).limit(1))
    has_models = result.scalar_one_or_none() is not None

    # Try to detect Ollama
    ollama_available = False
    ollama_models = []
    for base_url in ["http://localhost:11434", "http://host.docker.internal:11434"]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    ollama_available = True
                    data = resp.json()
                    ollama_models = [m["name"] for m in data.get("models", [])]
                    break
        except Exception:
            continue

    return {
        "has_models": has_models,
        "ollama_available": ollama_available,
        "ollama_models": ollama_models,
    }


@router.get("/settings/whisper", response_model=WhisperConfigResponse)
async def get_whisper_config(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> WhisperConfigResponse:
    """Get Whisper ASR configuration."""
    settings = get_settings()

    result = await db.execute(
        select(WhisperConfig).where(WhisperConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        # Return defaults from .env
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
        api_key_masked=_mask_key(
            decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key)
            if config.api_key_encrypted
            else None
        ),
        local_model=config.local_model,
    )


@router.put("/settings/whisper", response_model=WhisperConfigResponse)
async def update_whisper_config(
    data: WhisperConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
) -> WhisperConfigResponse:
    """Update Whisper ASR configuration."""
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
    await db.refresh(config)

    return WhisperConfigResponse(
        mode=config.mode,
        api_base_url=config.api_base_url,
        api_model=config.api_model,
        api_key_masked=_mask_key(
            decrypt_api_key(config.api_key_encrypted, settings.llm_encryption_key)
            if config.api_key_encrypted
            else None
        ),
        local_model=config.local_model,
    )


def _mask_key(key: str | None) -> str | None:
    """Mask an API key for display."""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


# ---------------------------------------------------------------------------
# Bilibili QR-code login
# ---------------------------------------------------------------------------


@router.post("/settings/bilibili/qrcode")
async def generate_bilibili_qrcode(
    user: Annotated[User, Depends(get_local_user)],
) -> dict:
    """Generate Bilibili QR code for scanning login."""
    import base64

    from bilibili_api.login_v2 import QrCodeLogin

    qr = QrCodeLogin()
    await qr.generate_qrcode()

    _bilibili_qr_sessions[str(user.id)] = qr

    b64 = base64.b64encode(qr.get_qrcode_picture().content).decode()
    return {"qrcode_base64": b64, "status": "generated"}


@router.get("/settings/bilibili/qrcode/status")
async def check_bilibili_qrcode(
    user: Annotated[User, Depends(get_local_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Check Bilibili QR code scan status and save credential on success."""
    from bilibili_api.login_v2 import QrCodeLoginEvents

    from app.db.models.bilibili_credential import BilibiliCredential

    qr = _bilibili_qr_sessions.get(str(user.id))
    if not qr:
        return {"status": "expired"}

    state = await qr.check_state()

    if state == QrCodeLoginEvents.SCAN:
        return {"status": "waiting"}
    elif state == QrCodeLoginEvents.CONF:
        return {"status": "scanned"}
    elif state == QrCodeLoginEvents.TIMEOUT:
        _bilibili_qr_sessions.pop(str(user.id), None)
        return {"status": "expired"}
    elif state == QrCodeLoginEvents.DONE:
        cred = qr.get_credential()
        settings = get_settings()

        # Upsert credential
        result = await db.execute(
            select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
        )
        bc = result.scalar_one_or_none()
        if not bc:
            bc = BilibiliCredential(user_id=user.id)
            db.add(bc)

        bc.sessdata_encrypted = encrypt_api_key(
            cred.sessdata, settings.llm_encryption_key
        )
        bc.bili_jct_encrypted = encrypt_api_key(
            cred.bili_jct, settings.llm_encryption_key
        )
        bc.dedeuserid = cred.dedeuserid

        await db.commit()
        _bilibili_qr_sessions.pop(str(user.id), None)

        return {"status": "done", "dedeuserid": cred.dedeuserid}

    return {"status": "unknown"}


@router.get("/settings/bilibili/status")
async def get_bilibili_status(
    user: Annotated[User, Depends(get_local_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Check if Bilibili credentials are configured."""
    from app.db.models.bilibili_credential import BilibiliCredential

    result = await db.execute(
        select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
    )
    bc = result.scalar_one_or_none()
    if bc and bc.sessdata_encrypted:
        return {"logged_in": True, "dedeuserid": bc.dedeuserid}
    return {"logged_in": False}


@router.delete("/settings/bilibili")
async def logout_bilibili(
    user: Annotated[User, Depends(get_local_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Remove stored Bilibili credentials."""
    from app.db.models.bilibili_credential import BilibiliCredential

    result = await db.execute(
        select(BilibiliCredential).where(BilibiliCredential.user_id == user.id)
    )
    bc = result.scalar_one_or_none()
    if bc:
        await db.delete(bc)
        await db.commit()
    return {"status": "logged_out"}
