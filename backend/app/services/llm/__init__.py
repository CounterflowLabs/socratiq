"""LLM abstraction layer public API."""

from app.services.llm.base import (
    ContentBlock,
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    StreamChunk,
    TokenUsage,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.config import ModelConfigManager
from app.services.llm.router import ModelRouter, TaskType
from app.services.llm.token_budget import (
    DEFAULT_LESSON_MAX_OUTPUT_TOKENS,
    DEFAULT_PROMPT_OVERHEAD_TOKENS,
    context_window_tokens,
    count_tokens,
    lesson_input_token_budget,
    lesson_max_output_tokens,
    truncate_to_tokens,
)

__all__ = [
    "ContentBlock",
    "DEFAULT_LESSON_MAX_OUTPUT_TOKENS",
    "DEFAULT_PROMPT_OVERHEAD_TOKENS",
    "LLMAuthError",
    "LLMError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMTimeoutError",
    "ModelConfigManager",
    "ModelRouter",
    "StreamChunk",
    "TaskType",
    "TokenUsage",
    "ToolDefinition",
    "UnifiedMessage",
    "context_window_tokens",
    "count_tokens",
    "lesson_input_token_budget",
    "lesson_max_output_tokens",
    "truncate_to_tokens",
]
