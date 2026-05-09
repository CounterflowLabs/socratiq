"""API routes for async task status (deprecated — use source/course progress)."""

from fastapi import APIRouter, Response
from celery.result import AsyncResult

from app.worker.celery_app import celery_app

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}/status", deprecated=True)
async def get_task_status(task_id: str, response: Response) -> dict:
    """Deprecated. Use ``GET /sources/{source_id}/progress`` instead.

    Reads from Celery's result backend (Redis), which has a TTL — once the
    result expires, ``state == "PENDING"`` is indistinguishable from "never
    queued". The DB-backed source progress endpoint is authoritative.
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 09 Jun 2026 00:00:00 GMT"
    response.headers["Link"] = (
        '</api/v1/sources/{source_id}/progress>; rel="successor-version"'
    )

    result = AsyncResult(task_id, app=celery_app)

    payload = {
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "SUCCESS":
        payload["result"] = result.result
    elif result.state == "FAILURE":
        payload["error"] = str(result.result)
    elif result.state == "PROGRESS" and result.info:
        payload["progress"] = result.info

    return payload
