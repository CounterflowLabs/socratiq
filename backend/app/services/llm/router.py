"""Model router: routes task types to LLM provider instances with caching."""

import time
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.base_url import normalize_container_localhost_url
from app.services.llm.config import ModelConfigManager
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.codex_provider import CodexProvider
from app.services.llm.openai_compat import OpenAICompatProvider


class TaskType(str, Enum):
    MENTOR_CHAT = "mentor_chat"
    CONTENT_ANALYSIS = "content_analysis"
    EVALUATION = "evaluation"
    # Structure planning — section bucketing, outline shaping. Decoupled
    # from EVALUATION (which is judge/grade) so the two can route to
    # different tiers as the routing table grows.
    STRUCTURE_PLANNING = "structure_planning"
    EMBEDDING = "embedding"
    # --- Orchestration tiers (Phase 2) -----------------------------------
    # New semantic routes for the agentic course-generation pipeline. They are
    # OPTIONAL: when a deployment hasn't mapped them in the model-config admin
    # UI, callers fall back through ``TASK_FALLBACKS`` to an existing route, so
    # nothing breaks with zero new config.
    PLANNING = "planning"          # heavy: outline shaping, sentence-explore
    JUDGMENT = "judgment"          # heavy: boundary / knowledge-point ReAct nodes
    CRITIC = "critic"              # mid: ModelCritic self-check
    BULK_ANALYSIS = "bulk_analysis"      # cheap: ContentAnalyzer bulk pass
    BULK_FORMATTING = "bulk_formatting"  # cheap: optional cheap lesson model


# Ordered fallbacks for the new orchestration routes → existing routes. The
# chain is handed to the LLM client (AgentRuntime/RouterLLMClient), NOT resolved
# inside the router: when ``get_provider(PLANNING)`` raises (no route row), the
# runtime's provider-fallback chain advances to the next entry. This keeps
# unconfigured deployments working without touching the routing table.
TASK_FALLBACKS: dict[TaskType, list[TaskType]] = {
    TaskType.PLANNING: [TaskType.STRUCTURE_PLANNING, TaskType.EVALUATION],
    TaskType.JUDGMENT: [TaskType.STRUCTURE_PLANNING],
    TaskType.CRITIC: [TaskType.EVALUATION],
    TaskType.BULK_ANALYSIS: [TaskType.CONTENT_ANALYSIS],
    TaskType.BULK_FORMATTING: [TaskType.CONTENT_ANALYSIS],
}


def resolve_chain(task: TaskType) -> list[TaskType]:
    """Return ``[task, *fallbacks]`` for use as a provider chain.

    Use as ``RouterLLMClient(router, primary=chain[0], fallbacks=chain[1:])``
    so an unconfigured new route degrades gracefully to a provisioned one.
    """
    return [task, *TASK_FALLBACKS.get(task, [])]


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
        context_window_tokens: int | None = None,
    ) -> LLMProvider:
        if provider_type == "anthropic":
            if not api_key:
                raise LLMError("Anthropic provider requires an API key")
            provider: LLMProvider = AnthropicProvider(
                model=model_id,
                api_key=api_key,
                max_tokens_limit=max_tokens_limit,
            )
        elif provider_type == "codex":
            provider = CodexProvider(
                model=model_id,
                supports_tools=False,
                supports_stream=False,
                max_tokens_limit=max_tokens_limit,
            )
        elif provider_type in {"openai", "openai_compatible"}:
            provider = OpenAICompatProvider(
                model=model_id,
                api_key=api_key,
                base_url=normalize_container_localhost_url(base_url),
                supports_tools=supports_tool_use,
                supports_stream=supports_streaming,
                max_tokens_limit=max_tokens_limit,
            )
        else:
            raise LLMError(f"Unknown provider type: {provider_type}")

        # Stamp the admin-declared context window onto the provider instance so
        # token-budget computation can prefer it over the lookup table. Only set
        # when configured — leaving it absent keeps the table/family fallback,
        # so unconfigured models behave exactly as before.
        if context_window_tokens is not None:
            provider._context_window = context_window_tokens
        return provider

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
            if task_type == TaskType.EMBEDDING and model.model_type != "embedding":
                raise LLMError(
                    f"Embedding route is configured to chat model '{model.name}'. "
                    "Configure a model with model_type='embedding'."
                )
            if task_type != TaskType.EMBEDDING and model.model_type == "embedding":
                raise LLMError(
                    f"Route '{task_type.value}' is configured to embedding model '{model.name}'. "
                    "Configure a chat model for this route."
                )

            api_key = self._config_manager.get_decrypted_api_key(model)

        provider = self._create_provider(
            provider_type=model.provider_type,
            model_id=model.model_id,
            api_key=api_key,
            base_url=model.base_url,
            supports_tool_use=model.supports_tool_use,
            supports_streaming=model.supports_streaming,
            max_tokens_limit=model.max_tokens_limit,
            context_window_tokens=model.context_window_tokens,
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
            context_window_tokens=model.context_window_tokens,
        )
        self._cache[f"name:{name}"] = (provider, time.time())
        return provider

    def invalidate_cache(self) -> None:
        """Clear all cached providers. Call when model configs are updated."""
        self._cache.clear()
