"""API routes for LLM model configuration management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.model_config import ModelConfig
from app.db.models.user import User
from app.models.model_schemas import (
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
    ModelTestResponse,
)
from app.services.llm.config import ModelConfigManager

router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _get_config_manager() -> ModelConfigManager:
    return ModelConfigManager(get_settings().llm_encryption_key)


@router.get("", response_model=list[ModelConfigResponse])
async def list_models(
    user: Annotated[User, Depends(get_local_user)],
    model_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    query = (
        select(ModelConfig)
        .where(or_(ModelConfig.user_id == user.id, ModelConfig.user_id.is_(None)))
    )
    if model_type is not None:
        query = query.where(ModelConfig.model_type == model_type)
    query = query.order_by(ModelConfig.name)
    result = await db.execute(query)
    models = list(result.scalars().all())
    return [
        ModelConfigResponse(
            name=m.name,
            provider_type=m.provider_type,
            model_id=m.model_id,
            api_key_masked=manager.get_masked_api_key(m),
            base_url=m.base_url,
            supports_tool_use=m.supports_tool_use,
            supports_streaming=m.supports_streaming,
            max_tokens_limit=m.max_tokens_limit,
            is_active=m.is_active,
            model_type=m.model_type,
        )
        for m in models
    ]


@router.post("", response_model=ModelConfigResponse, status_code=201)
async def create_model(
    data: ModelConfigCreate,
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    existing = await manager.get_model_by_name(db, data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Model '{data.name}' already exists")

    model = await manager.create_model(
        db,
        name=data.name,
        provider_type=data.provider_type,
        model_id=data.model_id,
        api_key=data.api_key,
        base_url=data.base_url,
        supports_tool_use=data.supports_tool_use,
        supports_streaming=data.supports_streaming,
        max_tokens_limit=data.max_tokens_limit,
    )
    model.user_id = user.id
    model.model_type = data.model_type
    await db.flush()

    # Auto-assign to tiers that don't have a model yet (type-aware)
    existing_tiers = await manager.get_tier_configs(db)
    assigned_tiers = {c.tier for c in existing_tiers}

    if data.model_type == "embedding":
        if "embedding" not in assigned_tiers:
            await manager.update_tier_config(db, "embedding", model.name)
    else:
        for tier in ["primary", "light", "strong"]:
            if tier not in assigned_tiers:
                await manager.update_tier_config(db, tier, model.name)

    return ModelConfigResponse(
        name=model.name,
        provider_type=model.provider_type,
        model_id=model.model_id,
        api_key_masked=manager.get_masked_api_key(model),
        base_url=model.base_url,
        supports_tool_use=model.supports_tool_use,
        supports_streaming=model.supports_streaming,
        max_tokens_limit=model.max_tokens_limit,
        is_active=model.is_active,
        model_type=model.model_type,
    )


@router.put("/{name}", response_model=ModelConfigResponse)
async def update_model(
    name: str,
    data: ModelConfigUpdate,
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    # Allow updating own models or system models
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.name == name,
            or_(ModelConfig.user_id == user.id, ModelConfig.user_id.is_(None)),
        )
    )
    model_obj = result.scalar_one_or_none()
    if not model_obj:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    update_data = data.model_dump(exclude_unset=True)
    model = await manager.update_model(db, name, **update_data)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    return ModelConfigResponse(
        name=model.name,
        provider_type=model.provider_type,
        model_id=model.model_id,
        api_key_masked=manager.get_masked_api_key(model),
        base_url=model.base_url,
        supports_tool_use=model.supports_tool_use,
        supports_streaming=model.supports_streaming,
        max_tokens_limit=model.max_tokens_limit,
        is_active=model.is_active,
        model_type=model.model_type,
    )


@router.delete("/{name}", status_code=204)
async def delete_model(
    name: str,
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    # Only allow deleting own models, not system models
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.name == name,
            ModelConfig.user_id == user.id,
        )
    )
    model_obj = result.scalar_one_or_none()
    if not model_obj:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    await db.delete(model_obj)
    await db.flush()


@router.post("/{name}/test", response_model=ModelTestResponse)
async def test_model(
    name: str,
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    """Test model connectivity by sending a simple prompt."""
    from app.services.llm.anthropic import AnthropicProvider
    from app.services.llm.openai_compat import OpenAICompatProvider
    from app.services.llm.base import UnifiedMessage, LLMError

    # Allow testing own models or system models
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.name == name,
            or_(ModelConfig.user_id == user.id, ModelConfig.user_id.is_(None)),
        )
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    api_key = manager.get_decrypted_api_key(model)

    try:
        from app.services.llm.openai_compat import OpenAICompatEmbeddingProvider

        if model.model_type == "embedding":
            provider = OpenAICompatEmbeddingProvider(
                model=model.model_id,
                api_key=api_key,
                base_url=model.base_url,
            )
        elif model.provider_type == "anthropic":
            provider = AnthropicProvider(model=model.model_id, api_key=api_key or "")
        else:
            provider = OpenAICompatProvider(
                model=model.model_id,
                api_key=api_key,
                base_url=model.base_url,
            )

        result = await provider.test_connectivity()
        return ModelTestResponse(
            success=result["success"],
            message=result["message"],
            model=result.get("model"),
            output=result.get("output"),
        )
    except LLMError as e:
        return ModelTestResponse(success=False, message=str(e))
    except Exception as e:
        return ModelTestResponse(success=False, message=f"Unexpected error: {e}")
