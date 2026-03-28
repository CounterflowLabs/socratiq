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
