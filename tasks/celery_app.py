"""
Celery 应用配置

配置 Celery 任务队列和 Worker。
支持任务路由、重试、超时等配置。
"""

from celery import Celery

from core.config import settings
from core.logging import setup_logging

# 配置日志
logger = setup_logging()

# 创建 Celery 应用
celery_app = Celery("condense_video")

# Celery 配置
celery_app.config_from_object(
    {
        # Broker 配置
        "broker_url": settings.celery_broker_url,
        "result_backend": settings.celery_result_backend,
        # 任务配置
        "task_track_started": True,  # 跟踪任务开始时间
        "task_time_limit": settings.task_timeout,  # 任务超时时间 (秒)
        "task_soft_time_limit": settings.task_timeout - 60,  # 软超时 (触发异常)
        "task_acks_late": True,  # 任务完成后才确认 (防止任务丢失)
        "worker_prefetch_multiplier": settings.worker_prefetch_multiplier,
        # 结果配置
        "result_expires": 86400,  # 结果保留 1 天
        "result_extended": True,  # 扩展结果信息
        # 序列化配置
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        # 时区配置
        "timezone": "Asia/Shanghai",
        "enable_utc": True,
        # 任务路由配置
        "task_routes": {
            "tasks.video.*": {"queue": "video"},
            "tasks.asr.*": {"queue": "asr"},
            "tasks.ppt.ocr": {"queue": "ocr"},
            "tasks.llm.*": {"queue": "llm"},
            "tasks.tts.*": {"queue": "tts"},
        },
        # 任务自动重试配置
        "task_autoretry_for": [
            "ConnectionError",
            "TimeoutError",
        ],
        "task_retry_max": 3,
        "task_retry_delay": 60,
        "task_retry_backoff": True,
        "task_retry_backoff_max": 600,
        "task_retry_jitter": True,
    }
)


# Celery Beat 配置 (用于定时任务)
celery_app.conf.beat_schedule = {
    # 示例: 每天凌晨清理过期数据
    # "cleanup-expired-tasks": {
    #     "task": "tasks.cleanup.cleanup_expired",
    #     "schedule": crontab(hour=2, minute=0),
    # },
}


@celery_app.task(bind=True)
def debug_task(self):
    """调试任务 - 用于测试 Celery 连接"""
    logger.info(f"Debug task called from {self.request.id}")
    return f"Debug task completed: {self.request.id}"


# Worker 启动入口
def worker_main():
    """Worker 启动入口"""
    celery_app.start()


if __name__ == "__main__":
    worker_main()
