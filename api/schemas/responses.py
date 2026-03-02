"""
API 响应 Schema 定义
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .common import ErrorDetail, HealthStatus, TaskStatus


# ==================== 基础响应 ====================


class ApiResponse(BaseModel):
    """通用 API 响应"""
    success: bool
    message: str
    data: Any | None = None


class ErrorResponse(BaseModel):
    """错误响应"""
    error: ErrorDetail


# ==================== 任务相关 ====================


class TaskResponse(BaseModel):
    """任务状态响应"""

    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0.0, le=1.0, description="进度 0.0 - 1.0")
    current_step: str | None = Field(default=None, description="当前步骤")
    message: str = Field(description="状态消息")
    created_at: datetime
    updated_at: datetime
    result: dict | None = Field(default=None, description="任务结果 (完成后)")


class TaskSubmitResponse(BaseModel):
    """任务提交响应"""

    task_id: str
    status: TaskStatus
    progress: float
    current_step: str | None
    message: str
    created_at: datetime
    updated_at: datetime


class TaskCancelResponse(BaseModel):
    """任务取消响应"""

    task_id: str
    status: TaskStatus
    message: str


class TaskLogEntry(BaseModel):
    """任务日志条目"""
    timestamp: datetime
    level: str
    step: str | None = None
    message: str


class TaskLogsResponse(BaseModel):
    """任务日志响应"""
    task_id: str
    logs: list[TaskLogEntry]


# ==================== 健康检查 ====================


class HealthCheck(BaseModel):
    """单个健康检查项"""
    status: HealthStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: HealthStatus
    checks: dict[str, HealthCheck]


class ConfigResponse(BaseModel):
    """配置信息响应"""
    ocr: dict
    classification: dict
    cutting_modes: dict
    tts: dict


# ==================== 进度推送 ====================


class ProgressMessage(BaseModel):
    """进度推送消息"""
    type: str = Field(description="消息类型: progress, step_complete, step_failed, task_complete, task_failed, task_cancelled")
    step: str
    progress: float = Field(ge=0.0, le=1.0)
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


# ==================== 文件下载 ====================


class FileInfo(BaseModel):
    """文件信息"""
    url: str
    filename: str
    size: int | None = None


# ==================== 视频处理结果 ====================


class ScriptFileInfo(BaseModel):
    """文稿步骤文件信息"""
    transcript_converted: FileInfo | None = None
    classification: FileInfo | None = None
    outline: FileInfo | None = None
    condensed_text: FileInfo | None = None
    summary: FileInfo | None = None
    key_points: FileInfo | None = None


class StepFileInfo(BaseModel):
    """步骤文件信息"""
    transcribe: dict | None = None
    ppt: dict | None = None
    audio: dict | None = None
    video: dict | None = None


class Statistics(BaseModel):
    """统计信息"""
    duration: float | None = None
    sentences: dict | None = None
    chapters_count: int | None = None


class ChapterInfo(BaseModel):
    """章节信息"""
    id: int
    title: str
    start_time: float
    end_time: float
    duration: float
    core_sentences: int
    keywords: list[str]
    key_formulas: list[str]


class VideoProcessResult(BaseModel):
    """视频处理结果"""

    # 视频输出
    condensed_video_url: str | None = None
    condensed_video_tts_url: str | None = None

    # 文稿输出
    script: ScriptFileInfo | None = None

    # 其他步骤
    steps: StepFileInfo | None = None

    # 统计信息
    statistics: Statistics | None = None

    # 章节信息
    chapters: list[ChapterInfo] = Field(default_factory=list)


class VideoFileInfo(BaseModel):
    """视频文件信息"""
    url: str
    filename: str
    size: int | None = None
    content_type: str


class VideoResultResponse(BaseModel):
    """视频结果响应"""
    video_id: str
    task_id: str
    status: TaskStatus
    result: VideoProcessResult | None = None
