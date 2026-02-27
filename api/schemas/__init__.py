"""
API Schema 模块

导出所有 API 请求和响应 Schema
"""

from .common import (
    ErrorCode,
    HealthStatus,
    ProcessingMode,
    STEP_WEIGHTS,
    TaskStep,
    TaskStatus,
    TTSEngine,
)
from .requests import (
    ProcessVideoRequest,
    TaskCancelRequest,
    VideoFileUpload,
)
from .responses import (
    ApiResponse,
    ChapterInfo,
    ConfigResponse,
    ErrorResponse,
    HealthCheck,
    HealthResponse,
    ProgressMessage,
    ScriptFileInfo,
    Statistics,
    StepFileInfo,
    TaskCancelResponse,
    TaskLogEntry,
    TaskLogsResponse,
    TaskResponse,
    TaskSubmitResponse,
    VideoProcessResult,
    VideoResultResponse,
)

__all__ = [
    # Common
    "ErrorCode",
    "HealthStatus",
    "ProcessingMode",
    "STEP_WEIGHTS",
    "TaskStep",
    "TaskStatus",
    "TTSEngine",
    # Requests
    "ProcessVideoRequest",
    "TaskCancelRequest",
    "VideoFileUpload",
    # Responses
    "ApiResponse",
    "ChapterInfo",
    "ConfigResponse",
    "ErrorResponse",
    "HealthCheck",
    "HealthResponse",
    "ProgressMessage",
    "ScriptFileInfo",
    "Statistics",
    "StepFileInfo",
    "TaskCancelResponse",
    "TaskLogEntry",
    "TaskLogsResponse",
    "TaskResponse",
    "TaskSubmitResponse",
    "VideoProcessResult",
    "VideoResultResponse",
]
