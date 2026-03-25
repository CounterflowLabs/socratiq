"""API routes for first-time setup / onboarding."""

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.model_config import ModelConfig

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/status")
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
