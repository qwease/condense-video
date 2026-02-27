"""
Redis 客户端测试
"""

import json
from datetime import datetime

import pytest
from redis import Redis

from core.config import AppConfig
from services.redis_client import (
    cancel_task,
    delete_task,
    get_progress,
    get_redis,
    get_result,
    get_task_status,
    list_active_tasks,
    save_result,
    set_task_status,
    subscribe_progress,
    update_progress,
)


@pytest.fixture
def redis_client():
    """Redis 客户端 fixture"""
    # 使用测试 Redis 实例
    client = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield client
    # 清理测试数据
    client.flushdb()


@pytest.fixture
def test_task_id():
    """测试任务 ID fixture"""
    return "test-task-123"


class TestRedisClient:
    """Redis 客户端测试"""

    def test_get_redis(self, redis_client):
        """测试获取 Redis 客户端"""
        client = get_redis()
        assert client is not None
        assert client.ping() is True

    def test_set_and_get_task_status(self, redis_client, test_task_id):
        """测试设置和获取任务状态"""
        # 设置任务状态
        set_task_status(
            task_id=test_task_id,
            status="pending",
            progress=0.0,
            current_step="init",
            message="Task initialized",
        )

        # 获取任务状态
        status = get_task_status(test_task_id)

        assert status is not None
        assert status["status"] == "pending"
        assert status["progress"] == 0.0
        assert status["current_step"] == "init"
        assert status["message"] == "Task initialized"
        assert "created_at" in status
        assert "updated_at" in status

    def test_update_task_status(self, redis_client, test_task_id):
        """测试更新任务状态"""
        # 初始化任务
        set_task_status(
            task_id=test_task_id,
            status="pending",
            progress=0.0,
        )

        # 更新状态
        set_task_status(
            task_id=test_task_id,
            status="processing",
            progress=0.5,
            current_step="asr",
            message="Processing audio",
        )

        # 验证更新
        status = get_task_status(test_task_id)

        assert status["status"] == "processing"
        assert status["progress"] == 0.5
        assert status["current_step"] == "asr"
        assert status["message"] == "Processing audio"
        # created_at 应该保持不变
        assert status["created_at"] == status["created_at"]

    def test_save_and_get_result(self, redis_client, test_task_id):
        """测试保存和获取结果"""
        result_data = {
            "success": True,
            "files": {"video": "/path/to/video.mp4"},
            "statistics": {"duration": 100.0},
        }

        # 保存结果
        save_result(test_task_id, result_data)

        # 获取结果
        result = get_result(test_task_id)

        assert result is not None
        assert result["success"] is True
        assert result["files"]["video"] == "/path/to/video.mp4"

    def test_update_and_get_progress(self, redis_client, test_task_id):
        """测试更新和获取进度"""
        progress_data = {
            "step": "asr_transcribe",
            "progress": 0.6,
            "message": "Transcribing audio",
            "data": {"processed": 60, "total": 100},
        }

        # 更新进度
        update_progress(
            task_id=test_task_id,
            step="asr_transcribe",
            progress=0.6,
            message="Transcribing audio",
            data={"processed": 60, "total": 100},
        )

        # 获取进度
        progress = get_progress(test_task_id)

        assert progress is not None
        assert progress["step"] == "asr_transcribe"
        assert progress["progress"] == 0.6
        assert progress["message"] == "Transcribing audio"
        assert progress["data"]["processed"] == 60
        assert "timestamp" in progress

    def test_cancel_task(self, redis_client, test_task_id):
        """测试取消任务"""
        # 创建待处理任务
        set_task_status(
            task_id=test_task_id,
            status="pending",
            progress=0.0,
        )

        # 取消任务
        result = cancel_task(test_task_id)

        assert result is True

        # 验证状态已更新
        status = get_task_status(test_task_id)
        assert status["status"] == "cancelled"

    def test_cancel_task_failed(self, redis_client, test_task_id):
        """测试取消已完成的任务"""
        # 创建已完成任务
        set_task_status(
            task_id=test_task_id,
            status="success",
            progress=1.0,
        )

        # 尝试取消
        result = cancel_task(test_task_id)

        assert result is False

    def test_delete_task(self, redis_client, test_task_id):
        """测试删除任务"""
        # 创建任务
        set_task_status(
            task_id=test_task_id,
            status="pending",
            progress=0.0,
        )
        save_result(test_task_id, {"success": True})

        # 删除任务
        delete_task(test_task_id)

        # 验证已删除
        assert get_task_status(test_task_id) is None
        assert get_progress(test_task_id) is None
        assert get_result(test_task_id) is None

    def test_list_active_tasks(self, redis_client):
        """测试列出活动任务"""
        # 创建多个任务
        for i in range(3):
            set_task_status(
                task_id=f"task-{i}",
                status="pending",
                progress=0.0,
            )

        # 创建一个已完成任务
        set_task_status(
            task_id="task-completed",
            status="success",
            progress=1.0,
        )

        # 列出活动任务
        active_tasks = list_active_tasks()

        assert len(active_tasks) == 3
        assert "task-0" in active_tasks
        assert "task-1" in active_tasks
        assert "task-2" in active_tasks
        assert "task-completed" not in active_tasks

    def test_subscribe_progress(self, redis_client, test_task_id):
        """测试订阅进度频道"""
        pubsub = subscribe_progress(test_task_id)

        assert pubsub is not None
        assert pubsub.connection is not None

        # 清理
        pubsub.unsubscribe(f"progress:{test_task_id}")
        pubsub.close()


@pytest.mark.integration
class TestRedisPubSub:
    """Redis Pub/Sub 集成测试"""

    def test_progress_publish_subscribe(self, redis_client, test_task_id):
        """测试进度发布和订阅"""
        # 订阅频道
        pubsub = subscribe_progress(test_task_id)
        pubsub.subscribe(f"progress:{test_task_id}")

        # 更新进度 (会发布到频道)
        update_progress(
            task_id=test_task_id,
            step="test_step",
            progress=0.5,
            message="Test message",
        )

        # 获取消息
        message = pubsub.get_message(timeout=1)
        assert message is not None
        assert message["type"] == "message"

        data = json.loads(message["data"])
        assert data["step"] == "test_step"
        assert data["progress"] == 0.5

        # 清理
        pubsub.unsubscribe(f"progress:{test_task_id}")
        pubsub.close()
