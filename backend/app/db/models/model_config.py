"""LLM model configuration and routing models."""

import uuid as uuid_module

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class ModelConfig(BaseMixin, Base):
    """Registered LLM provider/model configurations."""

    __tablename__ = "model_configs"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    supports_tool_use: Mapped[bool] = mapped_column(server_default=text("true"))
    supports_streaming: Mapped[bool] = mapped_column(server_default=text("true"))
    max_tokens_limit: Mapped[int] = mapped_column(server_default=text("4096"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    user_id: Mapped[uuid_module.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )


class ModelRouteConfig(BaseMixin, Base):
    """Maps task types to their configured model."""

    __tablename__ = "model_route_configs"

    task_type: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    model_name: Mapped[str] = mapped_column(
        String, ForeignKey("model_configs.name"), nullable=False
    )
    user_id: Mapped[uuid_module.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
