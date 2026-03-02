"""
Redis 客户端模块

提供统一的 Redis 操作接口，包括：
- 任务状态管理
- 进度跟踪
- 结果存储
- Pub/Sub 消息发布
"""

import json
from datetime import datetime
from typing import Any

from redis import Redis, ResponseError
from redis.retry import Retry
from redis.backoff import ExponentialBackoff

from core.config import settings
from core.exceptions import StorageException

import logging

logger = logging.getLogger(__name__)
# Redis 重试策略
# ExponentialBackoff doesn't take 'attempts' - the Retry count is the second arg
retry = Retry(ExponentialBackoff(), 3)

# Redis 客户端实例
redis: Redis | None = None


def get_redis() -> Redis:
    """
    获取 Redis 客户端实例

    使用单例模式，确保整个应用使用同一个连接。

    Returns:
        Redis 客户端实例

    Raises:
        StorageException: Redis 连接失败
    """
    global redis

    if redis is None:
        try:
            redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry=retry,
            )
            # 测试连接
            redis.ping()
            return redis
        except (OSError, ResponseError) as e:
            raise StorageException(f"Failed to connect to Redis: {e}") from e

    return redis


def close_redis() -> None:
    """关闭 Redis 连接"""
    global redis
    if redis is not None:
        redis.close()
        redis = None


# ==================== 任务状态 ====================


def set_task_status(
    task_id: str,
    status: str,
    progress: float = 0.0,
    current_step: str = "",
    message: str = "",
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """
    设置任务状态

    Args:
        task_id: 任务 ID
        status: 状态 (pending, processing, success, failed, cancelled)
        progress: 进度 (0.0 - 1.0)
        current_step: 当前步骤
        message: 状态消息
        result: 任务结果 (完成时)
        error: 错误信息 (失败时)
    """
    client = get_redis()
    if client is None:
        logger.warning(f"⚠️ Redis 未连接，跳过更新任务状态 (status: {status})")
        return

    key = f"task:{task_id}"
    now = datetime.now().isoformat()

    # 获取现有数据以保留 created_at
    existing = client.hgetall(key)
    created_at = existing.get("created_at", now)

    data: dict[str, str] = {
        "status": status,
        "progress": str(progress),
        "current_step": current_step,
        "message": message,
        "created_at": created_at,
        "updated_at": now,
    }

    if result:
        data["result_json"] = json.dumps(result, ensure_ascii=False)
    if error:
        data["error"] = error

    client.hset(key, mapping=data)
    client.expire(key, settings.redis_progress_ttl)


def get_task_status(task_id: str) -> dict[str, Any] | None:
    """
    获取任务状态

    Args:
        task_id: 任务 ID

    Returns:
        任务状态字典，如果任务不存在返回 None
    """
    client = get_redis()
    if client is None:
        logger.warning(f"⚠️ Redis 未连接，无法获取任务状态 (task_id: {task_id})")
        return None
        
    data = client.hgetall(f"task:{task_id}")

    if not data:
        return None

    # 转换类型
    if "progress" in data:
        data["progress"] = float(data["progress"])
    if "result_json" in data:
        data["result"] = json.loads(data["result_json"])

    return data


# ==================== 进度更新 ====================


def update_progress(
    task_id: str,
    step: str,
    progress: float,
    message: str,
    data: dict | None = None,
) -> None:
    """
    更新任务进度

    同时：
    1. 存储最新进度到 Redis
    2. 发布到 Pub/Sub 频道 (WebSocket 订阅)
    3. 更新任务状态

    Args:
        task_id: 任务 ID
        step: 当前步骤
        progress: 进度 (0.0 - 1.0)
        message: 进度消息
        data: 额外的进度数据
    """
    client = get_redis()
    if client is None:
        # 在没有 Redis 的情况下，只打印日志
        logger.info(f"[{step}] 进度: {progress*100:.1f}% - {message}")
        return
    
    key = f"task-progress:{task_id}"

    payload = {
        "step": step,
        "progress": progress,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now().isoformat(),
    }

    payload_json = json.dumps(payload, ensure_ascii=False)

    # 存储最新状态
    client.set(f"{key}:latest", payload_json, ex=settings.redis_progress_ttl)

    # 发布到频道 (WebSocket 订阅)
    client.publish(f"progress:{task_id}", payload_json)

    # 同步更新任务状态
    set_task_status(task_id, "processing", progress, step, message)


def get_progress(task_id: str) -> dict[str, Any] | None:
    """
    获取最新进度

    Args:
        task_id: 任务 ID

    Returns:
        进度信息字典，如果不存在返回 None
    """
    client = get_redis()
    data = client.get(f"task-progress:{task_id}:latest")
    return json.loads(data) if data else None


def subscribe_progress(task_id: str) -> Any:
    """
    订阅任务进度频道

    Args:
        task_id: 任务 ID

    Returns:
        Redis PubSub 对象
    """
    client = get_redis()
    pubsub = client.pubsub()
    pubsub.subscribe(f"progress:{task_id}")
    return pubsub


# ==================== 结果存储 ====================


def save_result(task_id: str, result: dict) -> None:
    """
    保存任务结果

    Args:
        task_id: 任务 ID
        result: 结果数据
    """
    client = get_redis()
    if client is None:
        logger.warning(f"⚠️ Redis 未连接，跳过保存任务结果 (task_id: {task_id})")
        return
        
    try:
        key = f"task-result:{task_id}"
        client.set(key, json.dumps(result, ensure_ascii=False), ex=settings.redis_result_ttl)
    except Exception as e:
        logger.error(f"保存结果到 Redis 失败: {e}")


def get_result(task_id: str) -> dict | None:
    """
    获取任务结果

    Args:
        task_id: 任务 ID

    Returns:
        结果字典，如果不存在返回 None
    """
    client = get_redis()
    data = client.get(f"task-result:{task_id}")
    return json.loads(data) if data else None


# ==================== 任务管理 ====================


def delete_task(task_id: str) -> None:
    """
    删除任务相关数据

    Args:
        task_id: 任务 ID
    """
    client = get_redis()
    keys = [
        f"task:{task_id}",
        f"task-progress:{task_id}:latest",
        f"task-result:{task_id}",
    ]
    client.delete(*keys)


def list_active_tasks() -> list[str]:
    """
    列出所有活动任务

    Returns:
        活动 (pending 或 processing) 任务 ID 列表
    """
    client = get_redis()
    pattern = "task:*"
    task_ids: list[str] = []

    for key in client.scan_iter(match=pattern):
        # key 格式: task:{task_id}
        parts = key.split(":")
        if len(parts) < 2:
            continue
        task_id = parts[1]
        status = client.hget(key, "status")
        if status in ["pending", "processing"]:
            task_ids.append(task_id)

    return task_ids


def cancel_task(task_id: str) -> bool:
    """
    取消任务

    Args:
        task_id: 任务 ID

    Returns:
        是否成功取消
    """
    client = get_redis()
    status = client.hget(f"task:{task_id}", "status")

    if status in ["pending", "processing"]:
        set_task_status(task_id, "cancelled", message="Task cancelled by user")
        return True

    return False


# ==================== 健康检查 ====================


def check_redis() -> dict[str, Any]:
    """
    检查 Redis 连接状态

    Returns:
        健康状态字典
    """
    try:
        client = get_redis()
        info = client.info()
        return {
            "status": "healthy",
            "connected": True,
            "used_memory_human": info.get("used_memory_human", "unknown"),
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(e),
        }
