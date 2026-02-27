"""
API 请求 Schema 定义
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .common import ProcessingMode, TTSEngine


class ProcessVideoRequest(BaseModel):
    """视频处理请求"""

    video_url: str | None = Field(
        default=None,
        description="视频 URL (与 video_file 二选一)",
        examples=["https://example.com/video.mp4"],
    )
    video_name: str = Field(
        default="video",
        description="视频名称 (用于输出目录命名)",
        examples=["lecture_01"],
    )
    mode: ProcessingMode = Field(
        default=ProcessingMode.ESSENTIAL,
        description="处理模式: essential (精要版) | complete (完整版)",
    )
    tts_engine: TTSEngine = Field(
        default=TTSEngine.DASHSCOPE,
        description="TTS 引擎: dashscope | edgetts",
    )
    voice: str = Field(
        default="Cherry",
        description="TTS 音色名称",
    )
    skip_transcribe: bool = Field(
        default=False,
        description="跳过转录步骤",
    )
    skip_ocr: bool = Field(
        default=False,
        description="跳过 OCR 步骤",
    )
    options: dict | None = Field(
        default=None,
        description="其他处理选项",
    )

    @field_validator("voice")
    @classmethod
    def validate_voice(cls, v: str, info) -> str:
        """验证音色配置"""
        tts_engine = info.data.get("tts_engine", TTSEngine.DASHSCOPE)
        if tts_engine == TTSEngine.DASHSCOPE:
            # DashScope CosyVoice 音色
            valid_voices = [
                "Cherry", "Kangkang", "Aijia", "Aida",
                "Aimei", "Aixia", "Aina", "Aitong",
                "Feynman", "Natasha", "Zhihui", "Yuejiang",
            ]
        else:
            # Edge TTS 音色
            valid_voices = [
                "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural",
                "zh-CN-YunyangNeural", "zh-CN-YunzeNeural",
            ]
        # 仅做警告，不强制限制
        return v


class VideoFileUpload(BaseModel):
    """视频文件上传参数"""
    file_name: str
    file_size: int
    content_type: Literal["video/mp4", "video/avi", "video/mkv", "video/mov", "video/flv"]


class TaskCancelRequest(BaseModel):
    """任务取消请求"""
    reason: str | None = Field(default=None, description="取消原因")
