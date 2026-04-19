"""API routes for LLM model routing configuration."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.config import get_settings
from app.db.models.user import User
from app.models.model_schemas import ModelRouteResponse, ModelRouteUpdate
from app.services.llm.config import ModelConfigManager

router = APIRouter(prefix="/api/v1/model-routes", tags=["model-routes"])


def _get_config_manager() -> ModelConfigManager:
    return ModelConfigManager(get_settings().llm_encryption_key)


@router.get("", response_model=list[ModelRouteResponse])
async def get_routes(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    routes = await manager.get_route_configs(db)
    return [
        ModelRouteResponse(task_type=r.task_type, model_name=r.model_name)
        for r in routes
    ]


@router.put("", response_model=list[ModelRouteResponse])
async def update_routes(
    routes: list[ModelRouteUpdate],
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    results = []
    for route in routes:
        model = await manager.get_model_by_name(db, route.model_name)
        if not model:
            raise HTTPException(status_code=404, detail=f"Model '{route.model_name}' not found")
        if route.task_type == "embedding" and model.model_type != "embedding":
            raise HTTPException(
                status_code=400,
                detail="Embedding route requires a model with model_type='embedding'",
            )
        if route.task_type != "embedding" and model.model_type == "embedding":
            raise HTTPException(
                status_code=400,
                detail=f"Route '{route.task_type}' requires a chat model, not an embedding model",
            )
        r = await manager.update_route_config(db, route.task_type, route.model_name)
        results.append(ModelRouteResponse(task_type=r.task_type, model_name=r.model_name))
    return results
