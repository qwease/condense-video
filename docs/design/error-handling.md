# 错误处理与监控 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. 统一错误处理

### 1.1 自定义异常

```python
# core/exceptions.py

from typing import Any


class AppException(Exception):
    """应用基础异常"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class VideoProcessingException(AppException):
    """视频处理异常"""
    pass


class ASRException(AppException):
    """ASR 转录异常"""
    pass


class OCRException(AppException):
    """OCR 识别异常"""
    pass


class LLMException(AppException):
    """LLM 调用异常"""
    pass


class TTSException(AppException):
    """TTS 生成异常"""
    pass


class StorageException(AppException):
    """存储异常"""
    pass


class TaskNotFoundException(AppException):
    """任务不存在异常"""
    def __init__(self, task_id: str):
        super().__init__(f"Task {task_id} not found", "TASK_NOT_FOUND")


class ValidationException(AppException):
    """参数验证异常"""
    pass
```

### 1.2 API 异常处理器

```python
# api/main.py

from fastapi import Request, status
from fastapi.responses import JSONResponse
from core.exceptions import (
    AppException, TaskNotFoundException, ValidationException
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """应用异常统一处理"""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details
            }
        }
    )


@app.exception_handler(TaskNotFoundException)
async def task_not_found_handler(request: Request, exc: TaskNotFoundException):
    """任务不存在异常"""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": {
                "code": "TASK_NOT_FOUND",
                "message": exc.message
            }
        }
    )


@app.exception_handler(ValidationException)
async def validation_exception_handler(request: Request, exc: ValidationException):
    """参数验证异常"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": exc.message,
                "details": exc.details
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """未捕获异常处理"""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误"
            }
        }
    )
```

## 2. 任务重试策略

### 2.1 重试装饰器

```python
# tasks/celery_app.py

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import httpx


def retry_with_backoff(
    max_attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 60.0
):
    """带指数退避的重试装饰器"""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=initial_wait, max=max_wait),
        retry=retry_if_exception_type((
            httpx.HTTPStatusError,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            TimeoutError
        )),
        reraise=True
    )
```

### 2.2 Celery 任务重试

```python
# tasks/asr/transcribe.py

from celery import Task
from core.exceptions import ASRException


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(httpx.HTTPStatusError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def transcribe_audio(self, audio_path: str) -> dict:
    """语音转录任务（自动重试）"""
    try:
        result = dashscope_client.transcribe(audio_path)
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            # 服务器错误，可重试
            raise self.retry(exc=e, countdown=60)
        raise ASRException(f"ASR failed with status {e.response.status_code}")
    except Exception as e:
        logger.error(f"ASR failed: {e}")
        raise ASRException(f"Transcription failed: {str(e)}")
```

### 2.3 重试配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `max_retries` | 3 | 最大重试次数 |
| `default_retry_delay` | 60 | 默认重试延迟 (秒) |
| `retry_backoff` | True | 启用指数退避 |
| `retry_backoff_max` | 600 | 最大退避时间 (秒) |
| `retry_jitter` | True | 添加随机抖动 |

## 3. 健康检查

```python
# api/routers/health.py

from fastapi import APIRouter
from services.redis_client import redis
from tasks.celery_app import celery_app
from core.storage import get_storage

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查"""
    checks = {
        "api": _check_api(),
        "redis": await _check_redis(),
        "celery": _check_celery(),
        "storage": await _check_storage()
    }

    is_healthy = all(c["status"] == "healthy" for c in checks.values())
    status_code = 200 if is_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if is_healthy else "unhealthy",
            "checks": checks
        }
    )


def _check_api() -> dict:
    """检查 API 状态"""
    return {"status": "healthy", "detail": "running"}


async def _check_redis() -> dict:
    """检查 Redis 连接"""
    try:
        redis.ping()
        return {"status": "healthy", "detail": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


def _check_celery() -> dict:
    """检查 Celery 状态"""
    try:
        inspector = celery_app.control.inspect()
        stats = inspector.stats()
        if stats:
            active_workers = len(stats)
            return {
                "status": "healthy",
                "detail": f"{active_workers} worker(s) active"
            }
        return {"status": "unhealthy", "detail": "no workers available"}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


async def _check_storage() -> dict:
    """检查存储服务"""
    try:
        storage = get_storage()
        # 执行简单检查
        return {"status": "healthy", "detail": settings.storage_backend}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}
```

## 4. 日志配置

```python
# core/logging.py

from loguru import logger
import sys
from pathlib import Path


def setup_logging():
    """配置日志"""
    # 移除默认处理器
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True
    )

    # 文件输出
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 所有日志
    logger.add(
        log_dir / "app.log",
        rotation="100 MB",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG"
    )

    # 错误日志
    logger.add(
        log_dir / "error.log",
        rotation="50 MB",
        retention="90 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR"
    )

    return logger


# Celery 任务日志
@celery_app.task.bind
def task_logger(self, task_id, retval, state, *args, **kwargs):
    """记录任务状态变化"""
    if state == "SUCCESS":
        logger.info(f"Task {task_id} completed successfully")
    elif state == "FAILURE":
        logger.error(f"Task {task_id} failed: {retval}")
    elif state == "STARTED":
        logger.info(f"Task {task_id} started")
```

## 5. 性能监控

### 5.1 Prometheus 指标

```python
# core/metrics.py

from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import Response


# 任务指标
tasks_total = Counter(
    "condense_video_tasks_total",
    "Total number of tasks",
    ["task_type", "status"]
)

task_duration = Histogram(
    "condense_video_task_duration_seconds",
    "Task processing duration",
    ["task_type"],
    buckets=[60, 300, 600, 1800, 3600]  # 1分钟到1小时
)

active_tasks = Gauge(
    "condense_video_active_tasks",
    "Number of active tasks",
    ["queue"]
)

# API 指标
api_requests_total = Counter(
    "condense_video_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"]
)

api_request_duration = Histogram(
    "condense_video_api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

# DashScope API 指标
dashscope_requests_total = Counter(
    "condense_video_dashscope_requests_total",
    "Total DashScope API requests",
    ["service", "status"]
)

dashscope_request_duration = Histogram(
    "condense_video_dashscope_request_duration_seconds",
    "DashScope API request duration",
    ["service"],
    buckets=[1, 5, 10, 30, 60]
)


@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    return Response(content=generate_latest(), media_type="text/plain")
```

### 5.2 中间件

```python
# api/middleware.py

import time
from fastapi import Request
from core.metrics import api_requests_total, api_request_duration


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """API 请求监控中间件"""
    start_time = time.time()

    response = await call_next(request)

    # 记录指标
    duration = time.time() - start_time
    api_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    api_request_duration.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)

    return response
```

## 6. 错误代码表

| 代码 | HTTP 状态 | 说明 |
|------|-----------|------|
| `TASK_NOT_FOUND` | 404 | 任务不存在 |
| `INVALID_VIDEO` | 400 | 无效的视频文件 |
| `VIDEO_TOO_LARGE` | 413 | 视频文件过大 |
| `ASR_TRANSCRIBE_FAILED` | 500 | ASR 转录失败 |
| `OCR_RECOGNITION_FAILED` | 500 | OCR 识别失败 |
| `LLM_CLASSIFICATION_FAILED` | 500 | LLM 分类失败 |
| `LLM_QUOTA_EXCEEDED` | 429 | LLM 配额超限 |
| `TTS_GENERATION_FAILED` | 500 | TTS 生成失败 |
| `VIDEO_EDIT_FAILED` | 500 | 视频剪辑失败 |
| `STORAGE_ERROR` | 500 | 存储错误 |
| `STORAGE_QUOTA_EXCEEDED` | 507 | 存储空间不足 |
| `VALIDATION_ERROR` | 422 | 参数验证失败 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

## 7. 告警规则

```yaml
# prometheus/alerts.yml

groups:
  - name: condense-video
    interval: 30s
    rules:
      # 任务失败率告警
      - alert: HighTaskFailureRate
        expr: rate(condense_video_tasks_total{status="failed"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "任务失败率过高"

      # Worker 宕机告警
      - alert: NoWorkersAvailable
        expr: condense_video_active_tasks < 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "没有可用的 Worker"

      # API 延迟告警
      - alert: HighAPILatency
        expr: histogram_quantile(0.95, rate(condense_video_api_request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API 响应延迟过高"

      # Redis 连接失败告警
      - alert: RedisConnectionFailed
        expr: up{job="redis"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis 连接失败"
```
