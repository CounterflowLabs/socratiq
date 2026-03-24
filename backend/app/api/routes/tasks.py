"""API routes for async task status."""

from fastapi import APIRouter, HTTPException
from celery.result import AsyncResult

from app.worker.celery_app import celery_app

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}/status")
async def get_task_status(task_id: str) -> dict:
    """Get the status of an async task."""
    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.result)
    elif result.state == "PROGRESS" and result.info:
        response["progress"] = result.info

    return response
