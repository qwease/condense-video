"""
WebSocket 路由

实时推送任务进度和状态更新。
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from services.redis_client import get_redis, subscribe_progress

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/tasks/{task_id}")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点 - 实时接收任务进度

    连接格式: `ws://host/ws/tasks/{task_id}`

    服务端推送的消息格式:
    ```json
    {
      "type": "progress",
      "step": "asr_transcribe",
      "progress": 0.5,
      "message": "正在转录语音... 50%",
      "data": {"processed": 150, "total": 300},
      "timestamp": "2026-02-27T10:05:00Z"
    }
    ```

    消息类型:
    - `progress`: 进度更新
    - `step_complete`: 步骤完成
    - `step_failed`: 步骤失败
    - `task_complete`: 任务完成
    - `task_failed`: 任务失败
    - `task_cancelled`: 任务取消

    客户端可以发送以下命令:
    - `{"action": "ping"}` - 保活心跳
    - `{"action": "subscribe"}` - 订阅进度 (自动)
    - `{"action": "unsubscribe"}` - 取消订阅
    """
    await websocket.accept()

    # 发送连接确认
    await _send_message(websocket, {
        "type": "connected",
        "task_id": task_id,
        "message": f"Subscribed to task {task_id} progress",
    })

    # 获取 Redis 客户端
    try:
        redis = get_redis()
    except Exception as e:
        await _send_error(websocket, f"Failed to connect to Redis: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    # 检查任务是否存在
    from services.redis_client import get_task_status, get_progress

    task_status = get_task_status(task_id)

    if not task_status:
        await _send_error(websocket, f"Task {task_id} not found")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 发送当前状态
    await _send_message(websocket, {
        "type": "status",
        "task_id": task_id,
        "status": task_status.get("status"),
        "progress": float(task_status.get("progress", 0.0)),
        "current_step": task_status.get("current_step"),
        "message": task_status.get("message", ""),
    })

    # 如果任务已完成，发送完成消息后关闭
    if task_status.get("status") in ["success", "failed", "cancelled"]:
        await _send_message(websocket, {
            "type": f"task_{task_status.get('status')}",
            "task_id": task_id,
            "progress": float(task_status.get("progress", 0.0)),
            "message": task_status.get("message", ""),
            "data": task_status.get("result"),
        })
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
        return

    # 订阅 Redis Pub/Sub
    pubsub = subscribe_progress(task_id)

    # 启动心跳任务
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))

    # 启动消息监听任务
    listener_task = asyncio.create_task(
        _listen_for_messages(websocket, pubsub, task_id)
    )

    try:
        # 等待任一任务完成
        done, pending = await asyncio.wait(
            [heartbeat_task, listener_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 取消未完成的任务
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await _send_error(websocket, f"Error: {e}")
    finally:
        # 取消订阅
        try:
            pubsub.unsubscribe(f"progress:{task_id}")
            pubsub.close()
        except Exception:
            pass

        await websocket.close()


# ==================== 辅助函数 ====================


async def _listen_for_messages(
    websocket: WebSocket,
    pubsub: Any,
    task_id: str,
) -> None:
    """
    监听 Redis Pub/Sub 消息并转发给客户端
    """
    from services.redis_client import get_task_status, get_progress

    # 检查任务状态的定时器
    check_interval = 2.0  # 每 2 秒检查一次

    while True:
        try:
            # 非阻塞获取消息
            message = pubsub.get_message(timeout=0.1)

            if message and message.get("type") == "message":
                # 解析消息
                data = json.loads(message["data"])
                await _send_message(websocket, data)

                # 检查是否完成
                if data.get("type") in ["task_complete", "task_failed", "task_cancelled"]:
                    return  # 退出循环

            # 定期检查任务状态 (防止 Pub/Sub 漏消息)
            status = get_task_status(task_id)
            if status and status.get("status") in ["success", "failed", "cancelled"]:
                # 发送最终状态
                await _send_message(websocket, {
                    "type": f"task_{status['status']}",
                    "task_id": task_id,
                    "progress": float(status.get("progress", 0.0)),
                    "message": status.get("message", ""),
                    "data": status.get("result"),
                })
                return

            await asyncio.sleep(check_interval)

        except asyncio.CancelledError:
            return
        except Exception as e:
            await _send_error(websocket, f"Error listening for messages: {e}")
            await asyncio.sleep(check_interval)


async def _heartbeat(websocket: WebSocket) -> None:
    """
    定时发送心跳消息
    """
    try:
        while True:
            await asyncio.sleep(30)  # 每 30 秒发送一次心跳
            await _send_message(websocket, {"type": "ping", "message": "heartbeat"})
    except asyncio.CancelledError:
        return
    except Exception:
        return


async def _send_message(websocket: WebSocket, data: dict) -> None:
    """发送消息到客户端"""
    try:
        await websocket.send_json(data)
    except Exception:
        pass


async def _send_error(websocket: WebSocket, message: str) -> None:
    """发送错误消息到客户端"""
    await _send_message(websocket, {
        "type": "error",
        "message": message,
    })
