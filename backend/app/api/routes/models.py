"""API routes for LLM model configuration management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.models.model_schemas import (
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
    ModelTestResponse,
)
from app.services.llm.config import ModelConfigManager

router = APIRouter(prefix="/api/models", tags=["models"])


def _get_config_manager() -> ModelConfigManager:
    return ModelConfigManager(get_settings().llm_encryption_key)


@router.get("", response_model=list[ModelConfigResponse])
async def list_models(
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    models = await manager.get_all_models(db)
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
        )
        for m in models
    ]


@router.post("", response_model=ModelConfigResponse, status_code=201)
async def create_model(
    data: ModelConfigCreate,
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
    )


@router.put("/{name}", response_model=ModelConfigResponse)
async def update_model(
    name: str,
    data: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
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
    )


@router.delete("/{name}", status_code=204)
async def delete_model(
    name: str,
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    deleted = await manager.delete_model(db, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")


@router.post("/{name}/test", response_model=ModelTestResponse)
async def test_model(
    name: str,
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    """Test model connectivity by sending a simple prompt."""
    from app.services.llm.anthropic import AnthropicProvider
    from app.services.llm.openai_compat import OpenAICompatProvider
    from app.services.llm.base import UnifiedMessage, LLMError

    model = await manager.get_model_by_name(db, name)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    api_key = manager.get_decrypted_api_key(model)

    try:
        if model.provider_type == "anthropic":
            provider = AnthropicProvider(model=model.model_id, api_key=api_key or "")
        else:
            provider = OpenAICompatProvider(
                model=model.model_id,
                api_key=api_key,
                base_url=model.base_url,
            )

        response = await provider.chat(
            [UnifiedMessage(role="user", content="Say 'hello' in one word.")],
            max_tokens=10,
        )
        return ModelTestResponse(
            success=True,
            message="Connection successful",
            model=response.model,
        )
    except LLMError as e:
        return ModelTestResponse(success=False, message=str(e))
    except Exception as e:
        return ModelTestResponse(success=False, message=f"Unexpected error: {e}")
