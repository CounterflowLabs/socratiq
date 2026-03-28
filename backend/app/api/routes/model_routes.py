"""API routes for LLM model tier configuration."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.model_config import ModelConfig
from app.db.models.user import User
from app.models.model_schemas import ModelTier, ModelTierResponse, ModelTierUpdate
from app.services.llm.config import ModelConfigManager

router = APIRouter(prefix="/api/v1/model-tiers", tags=["model-tiers"])


def _get_config_manager() -> ModelConfigManager:
    return ModelConfigManager(get_settings().llm_encryption_key)


@router.get("", response_model=list[ModelTierResponse])
async def get_tiers(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    configs = await manager.get_tier_configs(db)
    return [
        ModelTierResponse(tier=c.tier, model_name=c.model_name)
        for c in configs
    ]


@router.put("", response_model=list[ModelTierResponse])
async def update_tiers(
    tiers: list[ModelTierUpdate],
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    results = []
    for t in tiers:
        # Validate model type matches tier
        model_result = await db.execute(
            select(ModelConfig).where(ModelConfig.name == t.model_name)
        )
        model = model_result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model '{t.model_name}' not found")

        is_embedding_tier = t.tier == ModelTier.EMBEDDING
        is_embedding_model = model.model_type == "embedding"
        if is_embedding_tier != is_embedding_model:
            if is_embedding_tier:
                raise HTTPException(400, f"Embedding tier 只能使用向量模型，'{t.model_name}' 是对话模型")
            else:
                raise HTTPException(400, f"对话 tier 不能使用向量模型 '{t.model_name}'")

        c = await manager.update_tier_config(db, t.tier.value, t.model_name)
        results.append(ModelTierResponse(tier=c.tier, model_name=c.model_name))
    return results
