"""API routes for LLM model routing configuration."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import get_settings
from app.models.model_schemas import ModelRouteResponse, ModelRouteUpdate
from app.services.llm.config import ModelConfigManager

router = APIRouter(prefix="/api/model-routes", tags=["model-routes"])


def _get_config_manager() -> ModelConfigManager:
    return ModelConfigManager(get_settings().llm_encryption_key)


@router.get("", response_model=list[ModelRouteResponse])
async def get_routes(
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
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    results = []
    for route in routes:
        r = await manager.update_route_config(db, route.task_type, route.model_name)
        results.append(ModelRouteResponse(task_type=r.task_type, model_name=r.model_name))
    return results
