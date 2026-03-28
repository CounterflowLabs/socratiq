"""API routes for async task status."""

import logging

from fastapi import APIRouter, Query
from celery.result import AsyncResult

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# Map known exception patterns to user-friendly messages
_ERROR_MESSAGES: dict[str, str] = {
    "No model configured": "模型未配置，请在设置页面配置模型",
    "not found": "资源未找到，请重试",
    "timed out": "处理超时，请稍后重试",
    "rate limit": "API 调用频率超限，请稍后重试",
    "API key": "API Key 无效或已过期，请检查模型配置",
    "Connection": "连接失败，请检查网络或模型服务是否正常",
}


def _sanitize_error(raw_error: str) -> str:
    """Convert raw exception string to a user-friendly message."""
    for pattern, friendly_msg in _ERROR_MESSAGES.items():
        if pattern.lower() in raw_error.lower():
            return friendly_msg
    return "处理失败，请稍后重试"


@router.get("/{task_id}/status")
async def get_task_status(task_id: str, debug: bool = Query(False)) -> dict:
    """Get the status of an async task.

    Args:
        debug: If true, include raw error details (for development only).
    """
    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        raw_error = str(result.result)
        logger.error(f"Task {task_id} failed: {raw_error}")
        response["error"] = _sanitize_error(raw_error)
        if debug:
            response["error_detail"] = raw_error
    elif result.state == "PROGRESS" and result.info:
        response["progress"] = result.info
        response["stage"] = result.info.get("stage")
        if "estimated_remaining_seconds" in result.info:
            response["estimated_remaining_seconds"] = result.info["estimated_remaining_seconds"]

    return response


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    """Cancel a running task."""
    result = AsyncResult(task_id, app=celery_app)
    result.revoke(terminate=True)
    return {"task_id": task_id, "status": "cancelled"}
