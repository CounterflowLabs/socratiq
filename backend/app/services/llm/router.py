"""Model router: routes task types to LLM provider instances with caching."""

import time
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.config import ModelConfigManager
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.openai_compat import OpenAICompatProvider


class TaskType(str, Enum):
    MENTOR_CHAT = "mentor_chat"
    CONTENT_ANALYSIS = "content_analysis"
    EVALUATION = "evaluation"
    EMBEDDING = "embedding"


class ModelRouter:
    """Routes task types to LLM provider instances."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        encryption_key: str,
        cache_ttl: int = 300,
    ) -> None:
        self._session_factory = session_factory
        self._config_manager = ModelConfigManager(encryption_key)
        self._cache: dict[str, tuple[LLMProvider, float]] = {}
        self._cache_ttl = cache_ttl

    def _is_cache_valid(self, name: str) -> bool:
        if name not in self._cache:
            return False
        _, timestamp = self._cache[name]
        return (time.time() - timestamp) < self._cache_ttl

    def _create_provider(
        self,
        provider_type: str,
        model_id: str,
        api_key: str | None,
        base_url: str | None,
        supports_tool_use: bool,
        supports_streaming: bool,
        max_tokens_limit: int,
    ) -> LLMProvider:
        if provider_type == "anthropic":
            if not api_key:
                raise LLMError("Anthropic provider requires an API key")
            return AnthropicProvider(
                model=model_id,
                api_key=api_key,
                max_tokens_limit=max_tokens_limit,
            )
        elif provider_type == "openai_compatible":
            return OpenAICompatProvider(
                model=model_id,
                api_key=api_key,
                base_url=base_url,
                supports_tools=supports_tool_use,
                supports_stream=supports_streaming,
                max_tokens_limit=max_tokens_limit,
            )
        else:
            raise LLMError(f"Unknown provider type: {provider_type}")

    async def get_provider(self, task_type: TaskType) -> LLMProvider:
        """Get an LLM provider for the given task type."""
        cache_key = f"route:{task_type.value}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key][0]

        async with self._session_factory() as db:
            routes = await self._config_manager.get_route_configs(db)
            route = next((r for r in routes if r.task_type == task_type.value), None)
            if not route:
                raise LLMError(f"No model configured for task type: {task_type.value}")

            model = await self._config_manager.get_model_by_name(db, route.model_name)
            if not model:
                raise LLMError(f"Model '{route.model_name}' not found")
            if not model.is_active:
                raise LLMError(f"Model '{route.model_name}' is not active")

            api_key = self._config_manager.get_decrypted_api_key(model)

        provider = self._create_provider(
            provider_type=model.provider_type,
            model_id=model.model_id,
            api_key=api_key,
            base_url=model.base_url,
            supports_tool_use=model.supports_tool_use,
            supports_streaming=model.supports_streaming,
            max_tokens_limit=model.max_tokens_limit,
        )
        self._cache[cache_key] = (provider, time.time())
        return provider

    async def get_provider_by_name(self, name: str) -> LLMProvider:
        """Get an LLM provider by model config name."""
        if self._is_cache_valid(f"name:{name}"):
            return self._cache[f"name:{name}"][0]

        async with self._session_factory() as db:
            model = await self._config_manager.get_model_by_name(db, name)
            if not model:
                raise LLMError(f"Model '{name}' not found")
            if not model.is_active:
                raise LLMError(f"Model '{name}' is not active")

            api_key = self._config_manager.get_decrypted_api_key(model)

        provider = self._create_provider(
            provider_type=model.provider_type,
            model_id=model.model_id,
            api_key=api_key,
            base_url=model.base_url,
            supports_tool_use=model.supports_tool_use,
            supports_streaming=model.supports_streaming,
            max_tokens_limit=model.max_tokens_limit,
        )
        self._cache[f"name:{name}"] = (provider, time.time())
        return provider

    def invalidate_cache(self) -> None:
        """Clear all cached providers. Call when model configs are updated."""
        self._cache.clear()
