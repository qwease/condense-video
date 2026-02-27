"""
健康检查和系统信息路由
"""

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import PlainTextResponse

from core.config import settings
from schemas.responses import (
    ConfigResponse,
    HealthCheck,
    HealthResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, summary="健康检查")
async def health_check() -> HealthResponse:
    """
    检查系统各组件健康状态

    返回 API、Redis、Celery Worker 和存储的健康状态。
    """
    checks: dict[str, HealthCheck] = {}

    # API 状态
    checks["api"] = HealthCheck(status="healthy", detail="running")

    # Redis 状态
    checks["redis"] = _check_redis()

    # Celery Worker 状态
    checks["celery"] = _check_celery()

    # 存储状态
    checks["storage"] = _check_storage()

    # 判断整体状态
    all_healthy = all(check.status == "healthy" for check in checks.values())

    return HealthResponse(
        status="healthy" if all_healthy else "unhealthy",
        checks=checks,
    )


@router.get("/config", response_model=ConfigResponse, summary="获取当前配置")
async def get_config() -> ConfigResponse:
    """
    获取当前系统配置 (调试用)

    返回 OCR、分类、剪辑模式和 TTS 的配置信息。
    """
    return ConfigResponse(
        ocr={
            "concurrency": settings.ocr_concurrency,
            "model": settings.ocr_model,
            "rpm": settings.ocr_rpm,
        },
        classification={
            "concurrency": settings.classification_concurrency,
            "model": settings.classification_model,
            "batch_size": settings.classification_batch_size,
        },
        cutting_modes=settings.cutting_modes,
        tts={
            "engine": settings.tts_engine,
            "voice": settings.tts_voice,
            "max_length": settings.tts_max_length,
        },
    )


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus 指标")
async def get_metrics() -> str:
    """
    返回 Prometheus 格式的指标
    """
    # TODO: 实现实际指标收集
    metrics = [
        "# HELP condense_video_tasks_total Total number of tasks",
        '# TYPE condense_video_tasks_total gauge',
        'condense_video_tasks_total{status="pending"} 0',
        'condense_video_tasks_total{status="processing"} 0',
        'condense_video_tasks_total{status="success"} 0',
        'condense_video_tasks_total{status="failed"} 0',
        "",
        "# HELP condense_video_api_requests_total Total API requests",
        '# TYPE condense_video_api_requests_total counter',
        'condense_video_api_requests_total 0',
    ]
    return "\n".join(metrics)


# ==================== 辅助函数 ====================


def _check_redis() -> HealthCheck:
    """检查 Redis 状态"""
    try:
        from services.redis_client import check_redis

        result = check_redis()
        if result.get("status") == "healthy":
            return HealthCheck(
                status="healthy",
                detail=f"connected, {result.get('used_memory_human', 'unknown')} memory",
            )
        return HealthCheck(status="unhealthy", detail=result.get("error", "unknown"))
    except Exception as e:
        return HealthCheck(status="unhealthy", detail=str(e))


def _check_celery() -> HealthCheck:
    """检查 Celery Worker 状态"""
    try:
        from celery import current_app

        # 尝试获取活跃的 worker
        inspector = current_app.control.inspect()
        active_workers = inspector.active()

        if active_workers:
            worker_count = len(active_workers)
            return HealthCheck(status="healthy", detail=f"{worker_count} worker(s) active")
        return HealthCheck(status="unhealthy", detail="no active workers")
    except Exception as e:
        return HealthCheck(status="unhealthy", detail=str(e))


def _check_storage() -> HealthCheck:
    """检查存储状态"""
    try:
        from core.storage import get_storage

        storage = get_storage()
        if storage.health_check():
            backend = settings.storage_backend
            detail = f"{backend}"
            if backend == "minio" and settings.minio_endpoint:
                detail += f" at {settings.minio_endpoint}"
            elif backend == "s3" and settings.s3_endpoint:
                detail += f" at {settings.s3_endpoint}"
            return HealthCheck(status="healthy", detail=detail)
        return HealthCheck(status="unhealthy", detail="storage unhealthy")
    except Exception as e:
        return HealthCheck(status="unhealthy", detail=str(e))
