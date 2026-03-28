"""LLM model configuration management (DB-backed)."""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.model_config import ModelConfig, ModelTierConfig
from app.services.llm.encryption import encrypt_api_key, decrypt_api_key, mask_api_key


class ModelConfigManager:
    """CRUD operations for LLM model configurations."""

    def __init__(self, encryption_key: str) -> None:
        self._encryption_key = encryption_key

    async def get_all_models(self, db: AsyncSession) -> list[ModelConfig]:
        result = await db.execute(select(ModelConfig).order_by(ModelConfig.name))
        return list(result.scalars().all())

    async def get_model_by_name(self, db: AsyncSession, name: str) -> ModelConfig | None:
        result = await db.execute(select(ModelConfig).where(ModelConfig.name == name))
        return result.scalar_one_or_none()

    async def create_model(
        self,
        db: AsyncSession,
        *,
        name: str,
        provider_type: str,
        model_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        supports_tool_use: bool = True,
        supports_streaming: bool = True,
        max_tokens_limit: int = 4096,
    ) -> ModelConfig:
        encrypted_key = None
        if api_key:
            encrypted_key = encrypt_api_key(api_key, self._encryption_key)

        model = ModelConfig(
            name=name,
            provider_type=provider_type,
            model_id=model_id,
            api_key_encrypted=encrypted_key,
            base_url=base_url,
            supports_tool_use=supports_tool_use,
            supports_streaming=supports_streaming,
            max_tokens_limit=max_tokens_limit,
        )
        db.add(model)
        await db.flush()
        return model

    async def update_model(
        self,
        db: AsyncSession,
        name: str,
        **kwargs,
    ) -> ModelConfig | None:
        model = await self.get_model_by_name(db, name)
        if not model:
            return None

        # Handle api_key encryption
        if "api_key" in kwargs:
            api_key = kwargs.pop("api_key")
            if api_key:
                kwargs["api_key_encrypted"] = encrypt_api_key(api_key, self._encryption_key)
            else:
                kwargs["api_key_encrypted"] = None

        for key, value in kwargs.items():
            if hasattr(model, key):
                setattr(model, key, value)

        await db.flush()
        return model

    async def delete_model(self, db: AsyncSession, name: str) -> bool:
        model = await self.get_model_by_name(db, name)
        if not model:
            return False
        await db.delete(model)
        await db.flush()
        return True

    def get_decrypted_api_key(self, model: ModelConfig) -> str | None:
        if not model.api_key_encrypted:
            return None
        return decrypt_api_key(model.api_key_encrypted, self._encryption_key)

    def get_masked_api_key(self, model: ModelConfig) -> str | None:
        key = self.get_decrypted_api_key(model)
        if not key:
            return None
        return mask_api_key(key)

    # Tier config management
    async def get_tier_configs(self, db: AsyncSession) -> list[ModelTierConfig]:
        result = await db.execute(select(ModelTierConfig))
        return list(result.scalars().all())

    async def update_tier_config(
        self,
        db: AsyncSession,
        tier: str,
        model_name: str,
    ) -> ModelTierConfig:
        result = await db.execute(
            select(ModelTierConfig).where(ModelTierConfig.tier == tier)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.model_name = model_name
        else:
            existing = ModelTierConfig(tier=tier, model_name=model_name)
            db.add(existing)
        await db.flush()
        return existing

    # Backwards compat aliases
    get_route_configs = get_tier_configs

    async def update_route_config(
        self, db: AsyncSession, task_type: str, model_name: str
    ) -> ModelTierConfig:
        return await self.update_tier_config(db, task_type, model_name)
