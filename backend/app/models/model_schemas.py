"""Pydantic schemas for LLM model configuration API."""

from pydantic import BaseModel, Field


class ModelConfigCreate(BaseModel):
    name: str = Field(..., description="Unique alias for this model")
    provider_type: str = Field(..., description="anthropic or openai_compatible")
    model_id: str = Field(..., description="Actual model identifier")
    api_key: str | None = Field(None, description="API key (will be encrypted)")
    base_url: str | None = Field(None, description="Custom API endpoint URL")
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
    supports_tool_use: bool
    supports_streaming: bool
    max_tokens_limit: int
    is_active: bool


class ModelRouteUpdate(BaseModel):
    task_type: str = Field(..., description="mentor_chat, content_analysis, evaluation, or embedding")
    model_name: str = Field(..., description="Model config name to route to")


class ModelRouteResponse(BaseModel):
    task_type: str
    model_name: str


class ModelTestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
