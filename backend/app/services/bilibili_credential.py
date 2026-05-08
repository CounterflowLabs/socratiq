"""Helpers for resolving the active Bilibili credential.

Both the source-creation route (preflight check) and the Celery worker
(actual extraction) need the same answer to "does a usable Bilibili
credential exist?". Centralising the lookup here keeps them in sync.

Lookup order:
1. Stored DB credential (`BilibiliCredential.sessdata_encrypted`).
2. Environment fallback (`settings.bilibili_sessdata`).
"""

import logging

from bilibili_api import Credential
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.bilibili_credential import BilibiliCredential
from app.services.llm.encryption import decrypt_api_key

logger = logging.getLogger(__name__)


async def load_bilibili_credential(db: AsyncSession) -> Credential | None:
    """Return a usable Bilibili `Credential`, or `None` if none configured."""
    settings = get_settings()

    try:
        result = await db.execute(select(BilibiliCredential).limit(1))
        stored = result.scalar_one_or_none()
        if stored and stored.sessdata_encrypted:
            sessdata = decrypt_api_key(
                stored.sessdata_encrypted,
                settings.llm_encryption_key,
            )
            bili_jct = (
                decrypt_api_key(
                    stored.bili_jct_encrypted,
                    settings.llm_encryption_key,
                )
                if stored.bili_jct_encrypted
                else ""
            )
            return Credential(sessdata=sessdata, bili_jct=bili_jct)
    except Exception:
        logger.warning(
            "Failed to load stored Bilibili credential; falling back to env.",
            exc_info=True,
        )

    sessdata = getattr(settings, "bilibili_sessdata", "")
    if sessdata:
        return Credential(
            sessdata=sessdata,
            bili_jct=getattr(settings, "bilibili_bili_jct", ""),
            buvid3=getattr(settings, "bilibili_buvid3", ""),
        )

    return None


async def has_bilibili_credential(db: AsyncSession) -> bool:
    """Return True iff a Bilibili credential is configured (DB or env)."""
    settings = get_settings()

    try:
        result = await db.execute(select(BilibiliCredential).limit(1))
        stored = result.scalar_one_or_none()
        if stored and stored.sessdata_encrypted:
            return True
    except Exception:
        logger.warning(
            "Failed to read BilibiliCredential row; falling back to env.",
            exc_info=True,
        )

    return bool(getattr(settings, "bilibili_sessdata", ""))
