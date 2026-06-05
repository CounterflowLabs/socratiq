"""agentcore.llm — LLMClient interface over the existing provider stack.

Types are re-exported from ``app.services.llm.base`` (single source of truth);
``RouterLLMClient`` wraps ``ModelRouter`` + ``AgentRuntime``.
"""

from app.agentcore.llm.client import LLMClient, TurnResult
from app.agentcore.llm.router_client import RouterLLMClient
from app.agentcore.llm.types import (
    ContentBlock,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolDefinition,
    UnifiedMessage,
)

__all__ = [
    "LLMClient",
    "TurnResult",
    "RouterLLMClient",
    "ContentBlock",
    "LLMResponse",
    "StreamChunk",
    "TokenUsage",
    "ToolDefinition",
    "UnifiedMessage",
]
