"""
自定义异常模块

定义应用中使用的所有自定义异常类。
"""

from typing import Any


class AppException(Exception):
    """
    应用基础异常

    所有自定义异常的基类，提供统一的错误信息格式。

    Attributes:
        message: 错误消息
        code: 错误代码
        details: 额外的错误详情
    """

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，用于 API 响应"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class VideoProcessingException(AppException):
    """视频处理异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "VIDEO_PROCESSING_ERROR", details)


class ASRException(AppException):
    """ASR 转录异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "ASR_TRANSCRIBE_FAILED", details)


class OCRException(AppException):
    """OCR 识别异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "OCR_RECOGNITION_FAILED", details)


class LLMException(AppException):
    """LLM 调用异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "LLM_API_ERROR", details)


class LLMQuotaExceededException(AppException):
    """LLM 配额超限异常"""

    def __init__(self, message: str = "LLM API quota exceeded", details: dict | None = None):
        super().__init__(message, "LLM_QUOTA_EXCEEDED", details)


class TTSException(AppException):
    """TTS 生成异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "TTS_GENERATION_FAILED", details)


class StorageException(AppException):
    """存储异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "STORAGE_ERROR", details)


class StorageQuotaExceededException(AppException):
    """存储空间不足异常"""

    def __init__(self, message: str = "Storage quota exceeded", details: dict | None = None):
        super().__init__(message, "STORAGE_QUOTA_EXCEEDED", details)


class TaskNotFoundException(AppException):
    """任务不存在异常"""

    def __init__(self, task_id: str):
        super().__init__(f"Task {task_id} not found", "TASK_NOT_FOUND", {"task_id": task_id})


class ValidationException(AppException):
    """参数验证异常"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, "VALIDATION_ERROR", details)


class InvalidVideoException(ValidationException):
    """无效的视频文件异常"""

    def __init__(self, message: str = "Invalid video file", details: dict | None = None):
        super().__init__(message, details or {})


class VideoTooLargeException(ValidationException):
    """视频文件过大异常"""

    def __init__(self, max_size: int, actual_size: int | None = None):
        details = {"max_size": max_size}
        if actual_size is not None:
            details["actual_size"] = actual_size
        super().__init__(f"Video file too large (max {max_size} bytes)", "VIDEO_TOO_LARGE", details)


# 错误代码到 HTTP 状态码的映射
ERROR_STATUS_MAP: dict[str, int] = {
    "TASK_NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "VIDEO_TOO_LARGE": 413,
    "LLM_QUOTA_EXCEEDED": 429,
    "STORAGE_QUOTA_EXCEEDED": 507,
    # 默认 400
    "UNKNOWN_ERROR": 400,
    "VIDEO_PROCESSING_ERROR": 500,
    "ASR_TRANSCRIBE_FAILED": 500,
    "OCR_RECOGNITION_FAILED": 500,
    "LLM_API_ERROR": 500,
    "TTS_GENERATION_FAILED": 500,
    "STORAGE_ERROR": 500,
}


def get_http_status_for_error(error_code: str) -> int:
    """根据错误代码获取对应的 HTTP 状态码"""
    return ERROR_STATUS_MAP.get(error_code, 400)
