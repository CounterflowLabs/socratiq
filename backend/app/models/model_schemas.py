"""Pydantic schemas for LLM model configuration API."""

from enum import Enum

from pydantic import BaseModel, Field


class ModelTier(str, Enum):
    PRIMARY = "primary"
    LIGHT = "light"
    STRONG = "strong"
    EMBEDDING = "embedding"


class ModelConfigCreate(BaseModel):
    name: str = Field(..., description="Unique alias for this model")
    provider_type: str = Field(..., description="anthropic or openai_compatible")
    model_id: str = Field(..., description="Actual model identifier")
    api_key: str | None = Field(None, description="API key (will be encrypted)")
    base_url: str | None = Field(None, description="Custom API endpoint URL")
    model_type: str = Field("chat", description="'chat' or 'embedding'")
    supports_tool_use: bool = True
    supports_streaming: bool = True
    max_tokens_limit: int = 4096


class ModelConfigUpdate(BaseModel):
    provider_type: str | None = None
    model_id: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    supports_tool_use: bool | None = None
    supports_streaming: bool | None = None
    max_tokens_limit: int | None = None
    is_active: bool | None = None


class ModelConfigResponse(BaseModel):
    name: str
    provider_type: str
    model_id: str
    api_key_masked: str | None = None
    base_url: str | None = None
    model_type: str = "chat"
    supports_tool_use: bool
    supports_streaming: bool
    max_tokens_limit: int
    is_active: bool


class ModelTierUpdate(BaseModel):
    tier: ModelTier = Field(..., description="primary, light, strong, or embedding")
    model_name: str = Field(..., description="Model config name to assign to this tier")


class ModelTierResponse(BaseModel):
    tier: str
    model_name: str


class WhisperConfigResponse(BaseModel):
    mode: str = "api"
    api_base_url: str | None = None
    api_model: str | None = None
    api_key_masked: str | None = None
    local_model: str | None = None


class WhisperConfigUpdate(BaseModel):
    mode: str | None = None
    api_base_url: str | None = None
    api_model: str | None = None
    api_key: str | None = None  # Plain text, will be encrypted
    local_model: str | None = None


# Backwards compat aliases
ModelRouteUpdate = ModelTierUpdate
ModelRouteResponse = ModelTierResponse


class ModelTestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
    output: str | None = None
