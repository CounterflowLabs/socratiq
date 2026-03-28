"""LLM abstraction layer: unified types and abstract provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ContentBlock(BaseModel):
    """A single content block in a message."""
    type: Literal["text", "image", "tool_use", "tool_result"]
    # text block
    text: str | None = None
    # tool_use block
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    # tool_result block
    tool_result_content: str | None = None
    is_error: bool = False


class UnifiedMessage(BaseModel):
    """Provider-agnostic message format."""
    role: Literal["system", "user", "assistant", "tool_result"]
    content: str | list[ContentBlock]


class ToolDefinition(BaseModel):
    """Definition of a tool available to the LLM."""
    name: str
    description: str
    parameters: dict  # JSON Schema


class TokenUsage(BaseModel):
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    """Response from a non-streaming LLM call."""
    content: list[ContentBlock]
    model: str
    usage: TokenUsage | None = None
    stop_reason: str | None = None


class StreamChunk(BaseModel):
    """A single chunk in a streaming LLM response."""
    type: Literal["text_delta", "tool_use_start", "tool_use_delta", "tool_use_end", "message_end"]
    text: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input_delta: str | None = None
    usage: TokenUsage | None = None


# Error hierarchy
class LLMError(Exception):
    """Base exception for LLM operations."""
    pass

class LLMRateLimitError(LLMError):
    """Rate limit exceeded."""
    pass

class LLMAuthError(LLMError):
    """Authentication failed."""
    pass

class LLMTimeoutError(LLMError):
    """Request timed out."""
    pass

class LLMProviderError(LLMError):
    """Provider-side error (500, etc)."""
    pass


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Send a chat request and return the complete response."""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[UnifiedMessage],
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Send a chat request and return a streaming response."""
        ...

    @abstractmethod
    def supports_tool_use(self) -> bool:
        """Whether this provider supports native tool use."""
        ...

    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming."""
        ...

    @abstractmethod
    def model_id(self) -> str:
        """The model identifier for this provider instance."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of texts.

        Default implementation raises NotImplementedError.
        Providers that support embeddings should override this.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support embeddings")

    async def test_connectivity(self) -> dict:
        """Test provider connectivity. Returns dict with success, message, model."""
        response = await self.chat(
            [UnifiedMessage(role="user", content="Say 'hello' in one word.")],
            max_tokens=10,
        )
        return {"success": True, "message": "Connection successful", "model": response.model}


class EmbeddingProvider(LLMProvider):
    """Base class for embedding-only providers. Chat methods raise errors."""

    async def chat(self, messages, **kwargs) -> LLMResponse:
        raise LLMError(f"{type(self).__name__} is an embedding model and does not support chat")

    async def chat_stream(self, messages, **kwargs):
        raise LLMError(f"{type(self).__name__} is an embedding model and does not support chat")

    def supports_tool_use(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False

    async def test_connectivity(self) -> dict:
        """Test embedding connectivity."""
        embeddings = await self.embed(["hello"])
        return {
            "success": True,
            "message": f"Connection successful (embedding dim={len(embeddings[0])})",
            "model": self.model_id(),
        }
