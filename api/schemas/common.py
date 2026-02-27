"""
通用 API Schema 定义
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCode(str, Enum):
    """错误代码枚举"""
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    INVALID_VIDEO = "INVALID_VIDEO"
    ASR_TRANSCRIBE_FAILED = "ASR_TRANSCRIBE_FAILED"
    OCR_RECOGNITION_FAILED = "OCR_RECOGNITION_FAILED"
    LLM_CLASSIFICATION_FAILED = "LLM_CLASSIFICATION_FAILED"
    TTS_GENERATION_FAILED = "TTS_GENERATION_FAILED"
    VIDEO_EDIT_FAILED = "VIDEO_EDIT_FAILED"
    STORAGE_ERROR = "STORAGE_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProcessingMode(str, Enum):
    """处理模式枚举"""
    ESSENTIAL = "essential"  # 精要版
    COMPLETE = "complete"    # 完整版


class TTSEngine(str, Enum):
    """TTS 引擎枚举"""
    DASHSCOPE = "dashscope"
    EDGETTS = "edgetts"


class TaskStep(str, Enum):
    """任务步骤枚举"""
    VIDEO_DOWNLOAD = "video_download"
    AUDIO_EXTRACT = "audio_extract"
    PPT_EXTRACT = "ppt_extract"
    ASR_TRANSCRIBE = "asr_transcribe"
    PPT_OCR = "ppt_ocr"
    CONTENT_CLASSIFY = "content_classify"
    CHAPTER_SEGMENT = "chapter_segment"
    CONTENT_SUMMARIZE = "content_summarize"
    TTS_GENERATE = "tts_generate"
    VIDEO_EDIT = "video_edit"
    CLEANUP = "cleanup"


# 步骤权重 (进度计算)
STEP_WEIGHTS: dict[TaskStep, float] = {
    TaskStep.VIDEO_DOWNLOAD: 0.05,
    TaskStep.AUDIO_EXTRACT: 0.05,
    TaskStep.PPT_EXTRACT: 0.05,
    TaskStep.ASR_TRANSCRIBE: 0.15,
    TaskStep.PPT_OCR: 0.15,
    TaskStep.CONTENT_CLASSIFY: 0.10,
    TaskStep.CHAPTER_SEGMENT: 0.05,
    TaskStep.CONTENT_SUMMARIZE: 0.10,
    TaskStep.TTS_GENERATE: 0.15,
    TaskStep.VIDEO_EDIT: 0.10,
    TaskStep.CLEANUP: 0.05,
}


class ErrorDetail(BaseModel):
    """错误详情"""
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class HealthStatus(str, Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
