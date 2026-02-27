"""
任务管理路由

处理任务的查询、取消、日志获取等操作。
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import UUID

from schemas.common import ErrorCode, TaskStatus
from schemas.requests import TaskCancelRequest
from schemas.responses import (
    ErrorResponse,
    TaskCancelResponse,
    TaskLogEntry,
    TaskLogsResponse,
    TaskResponse,
)
from services.redis_client import (
    cancel_task,
    get_progress,
    get_result,
    get_task_status,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskResponse, summary="查询任务状态")
async def get_task(task_id: str) -> TaskResponse:
    """
    查询指定任务的状态和进度

    - **task_id**: 任务 UUID
    - 返回任务当前状态、进度、步骤等信息
    - 如果任务完成，result 字段包含结果数据
    """
    # 获取任务状态
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Task {task_id} not found",
                    "details": {"task_id": task_id},
                }
            ).model_dump(),
        )

    # 解析状态
    try:
        task_status = TaskStatus(task_data["status"])
    except ValueError:
        task_status = TaskStatus.PENDING

    # 获取结果 (如果完成)
    result = task_data.get("result")
    if task_status == TaskStatus.SUCCESS and not result:
        result = get_result(task_id)

    return TaskResponse(
        task_id=task_id,
        status=task_status,
        progress=task_data.get("progress", 0.0),
        current_step=task_data.get("current_step"),
        message=task_data.get("message", ""),
        created_at=datetime.fromisoformat(task_data["created_at"]),
        updated_at=datetime.fromisoformat(task_data["updated_at"]),
        result=result,
    )


@router.delete(
    "/{task_id}",
    response_model=TaskCancelResponse,
    summary="取消任务",
)
async def cancel_task_endpoint(
    task_id: str,
    request: TaskCancelRequest | None = None,
) -> TaskCancelResponse:
    """
    取消正在执行的任务

    - **task_id**: 任务 UUID
    - 仅 pending 或 processing 状态的任务可以取消
    - 已完成或失败的任务无法取消
    """
    # 检查任务是否存在
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Task {task_id} not found",
                    "details": {"task_id": task_id},
                }
            ).model_dump(),
        )

    # 检查任务状态
    current_status = task_data.get("status")
    if current_status not in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": f"Cannot cancel task with status {current_status}",
                    "details": {"task_id": task_id, "status": current_status},
                }
            ).model_dump(),
        )

    # 执行取消
    success = cancel_task(task_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": "Failed to cancel task",
                    "details": {"task_id": task_id},
                }
            ).model_dump(),
        )

    # 撤销 Celery 任务
    try:
        from celery import current_app

        current_app.control.revoke(task_id, terminate=True)
    except Exception:
        pass  # 忽略 Celery 撤销失败

    reason_msg = f"Reason: {request.reason}" if request and request.reason else "No reason provided"

    return TaskCancelResponse(
        task_id=task_id,
        status=TaskStatus.CANCELLED,
        message=f"Task cancelled. {reason_msg}",
    )


@router.get(
    "/{task_id}/logs",
    response_model=TaskLogsResponse,
    summary="获取任务日志",
)
async def get_task_logs(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数"),
) -> TaskLogsResponse:
    """
    获取任务的执行日志

    - **task_id**: 任务 UUID
    - **limit**: 返回的最大日志条数 (1-1000)
    - 返回按时间倒序排列的日志列表
    """
    # TODO: 实现日志存储和查询
    # 当前 Redis 仅存储进度，未存储详细日志
    # 可以考虑:
    # 1. 使用 Redis List 存储日志
    # 2. 使用专门的日志数据库
    # 3. 从文件系统读取日志文件

    # 检查任务是否存在
    task_data = get_task_status(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Task {task_id} not found",
                    "details": {"task_id": task_id},
                }
            ).model_dump(),
        )

    # 暂时返回当前状态作为日志
    logs = [
        TaskLogEntry(
            timestamp=datetime.fromisoformat(task_data["updated_at"]),
            level="INFO",
            step=task_data.get("current_step"),
            message=task_data.get("message", ""),
        )
    ]

    return TaskLogsResponse(task_id=task_id, logs=logs)


@router.get(
    "/{task_id}/progress",
    summary="获取任务进度",
)
async def get_task_progress(task_id: str) -> dict[str, Any]:
    """
    获取任务的最新进度信息

    - **task_id**: 任务 UUID
    - 返回实时进度数据
    """
    progress = get_progress(task_id)

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error={
                    "code": ErrorCode.TASK_NOT_FOUND,
                    "message": f"Task {task_id} not found or no progress available",
                    "details": {"task_id": task_id},
                }
            ).model_dump(),
        )

    return progress
