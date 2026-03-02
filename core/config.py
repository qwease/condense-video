"""
配置管理模块

所有配置均通过 .env 文件管理，无需修改代码。
"""

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class DashScopeConfig(BaseModel):
    """DashScope API 配置"""

    api_key: str
    asr_model: str = "paraformer-v2"
    ocr_model: str = "qwen-vl-plus"
    llm_model: str = "qwen-plus"
    tts_model: str = "qwen3-tts-flash"
    rpm: int = 60
    retry_times: int = 3
    retry_delay: int = 1000


class AppConfig(BaseSettings):
    """
    应用配置 - 全部支持 .env 覆盖

    使用 pydantic-settings 从环境变量和 .env 文件加载配置。
    环境变量优先级高于 .env 文件。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="allow",
    )

    # ============== API 配置 ==============
    api_host: str = Field(default="0.0.0.0", alias="API_HOST", description="API 服务监听地址")
    api_port: int = Field(default=8000, alias="API_PORT", description="API 服务端口")
    api_workers: int = Field(default=1, alias="API_WORKERS", description="API 工作进程数")
    api_reload: bool = Field(default=False, alias="API_RELOAD", description="开发模式自动重载")
    api_debug: bool = Field(default=False, alias="API_DEBUG", description="调试模式 - 输出详细日志")

    # ============== Celery 配置 ==============
    celery_broker_url: str = Field(
        default="redis://redis:6379/0",
        alias="CELERY_BROKER_URL",
        description="Celery 消息队列 URL"
    )
    celery_result_backend: str = Field(
        default="redis://redis:6379/0",
        alias="CELERY_RESULT_BACKEND",
        description="Celery 结果存储 URL"
    )
    worker_concurrency: int = Field(default=2, alias="WORKER_CONCURRENCY", description="Worker 并发数")
    worker_prefetch_multiplier: int = Field(
        default=4,
        alias="WORKER_PREFETCH_MULTIPLIER",
        description="Worker 预取倍数"
    )

    # ============== Redis 配置 ==============
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL", description="Redis 连接 URL")
    redis_progress_ttl: int = Field(
        default=604800,
        alias="REDIS_PROGRESS_TTL",
        description="任务进度缓存时间 (秒)，默认 7 天"
    )
    redis_result_ttl: int = Field(
        default=2592000,
        alias="REDIS_RESULT_TTL",
        description="任务结果缓存时间 (秒)，默认 30 天"
    )

    # ============== 存储配置 ==============
    storage_backend: Literal["local", "minio", "s3", "uuguu"] = Field(
        default="local",
        alias="STORAGE_BACKEND",
        description="存储后端类型"
    )
    storage_path: str = Field(default="./data", alias="STORAGE_PATH", description="本地存储路径")

    # MinIO 配置
    minio_endpoint: str | None = Field(default=None, alias="MINIO_ENDPOINT", description="MinIO 服务地址")
    minio_access_key: str | None = Field(default=None, alias="MINIO_ACCESS_KEY", description="MinIO 访问密钥")
    minio_secret_key: str | None = Field(default=None, alias="MINIO_SECRET_KEY", description="MinIO 秘密密钥")
    minio_bucket: str = Field(default="condense-video", alias="MINIO_BUCKET", description="MinIO 存储桶名称")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE", description="MinIO 是否使用 HTTPS")

    # S3 配置
    s3_endpoint: str | None = Field(default=None, alias="S3_ENDPOINT", description="S3 服务地址")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID", description="S3 访问密钥 ID")
    s3_secret_access_key: str | None = Field(
        default=None,
        alias="S3_SECRET_ACCESS_KEY",
        description="S3 秘密访问密钥"
    )
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET", description="S3 存储桶名称")
    s3_region: str | None = Field(default=None, alias="S3_REGION", description="S3 区域")

    # ============== DashScope 配置 ==============
    dashscope_api_key: str = Field(..., alias="DASHSCOPE_API_KEY", description="DashScope API 密钥 (必需)")
    dashscope_asr_model: str = Field(
        default="paraformer-v2",
        alias="DASHSCOPE_ASR_MODEL",
        description="DashScope ASR 模型"
    )
    dashscope_ocr_model: str = Field(
        default="qwen-vl-plus",
        alias="DASHSCOPE_OCR_MODEL",
        description="DashScope OCR 模型"
    )
    dashscope_llm_model: str = Field(
        default="qwen-plus",
        alias="DASHSCOPE_LLM_MODEL",
        description="DashScope LLM 模型"
    )
    dashscope_tts_model: str = Field(
        default="qwen3-tts-flash",
        alias="DASHSCOPE_TTS_MODEL",
        description="DashScope TTS 模型"
    )

    # ============== OCR 配置 ==============
    ocr_model: str = Field(default="qwen-vl-plus", alias="OCR_MODEL", description="OCR 模型")
    ocr_concurrency: int = Field(default=5, alias="OCR_CONCURRENCY", description="OCR 并发数")
    ocr_rpm: int = Field(default=60, alias="OCR_RPM", description="OCR 每分钟请求限制")
    ocr_retry_times: int = Field(default=3, alias="OCR_RETRY_TIMES", description="OCR 重试次数")
    ocr_retry_delay: int = Field(default=1000, alias="OCR_RETRY_DELAY", description="OCR 重试延迟 (毫秒)")

    # ============== 内容分类配置 ==============
    classification_provider: str = Field(
        default="dashscope",
        alias="CLASSIFICATION_PROVIDER",
        description="分类服务提供商"
    )
    classification_model: str = Field(default="qwen-plus", alias="CLASSIFICATION_MODEL", description="分类模型")
    classification_concurrency: int = Field(default=10, alias="CLASSIFICATION_CONCURRENCY", description="分类并发数")
    classification_batch_size: int = Field(default=50, alias="CLASSIFICATION_BATCH_SIZE", description="分类批处理大小")

    # ============== 帧提取配置 ==============
    frame_scene_threshold: float = Field(
        default=0.3,
        alias="FRAME_SCENE_THRESHOLD",
        description="场景变化阈值 (0-1)"
    )
    frame_min_interval: int = Field(default=2, alias="FRAME_MIN_INTERVAL", description="最小帧间隔 (秒)")
    frame_max_width: int = Field(default=1920, alias="FRAME_MAX_WIDTH", description="最大帧宽度 (像素)")
    sample_interval_sec: int = Field(default=1, alias="SAMPLE_INTERVAL_SEC", description="采样间隔 (秒)")
    phash_size: int = Field(default=16, alias="PHASH_SIZE", description="PHASH 哈希大小")
    similarity_threshold: float = Field(default=20, alias="PHASH_SIMILARITY_THRESHOLD", description="PHASH 相似度阈值")
    max_frames: int = Field(default=0, alias="PPT_MAX_FRAMES", description="最大处理帧数")
    min_content_ratio: float = Field(default=0.15, alias="PPT_MIN_CONTENT_RATIO", description="最小内容比例")
    output_width: int = Field(default=1920, alias="PPT_OUTPUT_WIDTH", description="输出图片宽度")
    output_quality: int = Field(default=85, alias="PPT_OUTPUT_QUALITY", description="JPEG 质量")
    enable_slide_filter: bool = Field(default=True, alias="PPT_ENABLE_SLIDE_FILTER", description="启用PPT内容过滤")
    enable_stability_check: bool = Field(default=True, alias="PPT_ENABLE_STABILITY_CHECK", description="稳定性检测（较慢，按需开启）")
    stability_seconds: int = Field(default=1, alias="PPT_STABILITY_SECONDS", description="稳定性检测窗口（秒）")
    min_frames_for_parallel: int = Field(default=3000, alias="PPT_MIN_FRAMES_FOR_PARALLEL", description="并行处理最小帧数")
    num_workers: int = Field(default=8, alias="PPT_NUM_WORKERS", description="并行处理工作线程数")

    # ============== 剪辑配置 ==============
    cutting_mode_essential_delete_labels: str = Field(
        default="interact,chat,transition",
        alias="CUTTING_MODE_ESSENTIAL_DELETE_LABELS",
        description="精要版删除标签 (逗号分隔)"
    )
    cutting_mode_complete_delete_labels: str = Field(
        default="chat",
        alias="CUTTING_MODE_COMPLETE_DELETE_LABELS",
        description="完整版删除标签 (逗号分隔)"
    )
    cutting_buffer_ms: int = Field(default=50, alias="CUTTING_BUFFER_MS", description="剪辑缓冲时间 (毫秒)")
    cutting_crossfade_ms: int = Field(default=30, alias="CUTTING_CROSSFADE_MS", description="交叉淡入淡出时间 (毫秒)")

    # ============== TTS 配置 ==============
    tts_engine: Literal["dashscope", "edgetts"] = Field(
        default="dashscope",
        alias="TTS_ENGINE",
        description="TTS 引擎类型"
    )
    tts_voice: str = Field(default="Cherry", alias="TTS_VOICE", description="TTS 音色")
    tts_max_length: int = Field(default=300, alias="TTS_MAX_LENGTH", description="TTS 单段最大长度 (字符)")
    tts_concurrency: int = Field(default=3, alias="TTS_CONCURRENCY", description="TTS 并发数")

    # Edge TTS 特定配置
    edgetts_voice: str = Field(
        default="zh-CN-XiaoxiaoNeural",
        alias="EDGETTS_VOICE",
        description="Edge TTS 音色"
    )
    edgetts_rate: int = Field(default=0, alias="EDGETTS_RATE", description="Edge TTS 语速调整")
    edgetts_volume: int = Field(default=0, alias="EDGETTS_VOLUME", description="Edge TTS 音量调整")

    # ============== 任务配置 ==============
    task_timeout: int = Field(default=7200, alias="TASK_TIMEOUT", description="任务超时时间 (秒)，默认 2 小时")
    task_max_retries: int = Field(default=3, alias="TASK_MAX_RETRIES", description="任务最大重试次数")

    @field_validator("dashscope_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """验证 API 密钥格式"""
        if not v or not v.startswith("sk-"):
            raise ValueError("DASHSCOPE_API_KEY must start with 'sk-'")
        return v

    @property
    def cutting_modes(self) -> dict:
        """解析剪辑模式配置"""
        return {
            "essential": {
                "description": "精要版 - 仅保留核心知识",
                "delete_labels": self.cutting_mode_essential_delete_labels.split(","),
            },
            "complete": {
                "description": "完整版 - 保留核心+解释",
                "delete_labels": self.cutting_mode_complete_delete_labels.split(","),
            },
        }

    @property
    def dashscope(self) -> DashScopeConfig:
        """获取 DashScope 配置对象"""
        return DashScopeConfig(
            api_key=self.dashscope_api_key,
            asr_model=self.dashscope_asr_model,
            ocr_model=self.dashscope_ocr_model,
            llm_model=self.dashscope_llm_model,
            tts_model=self.dashscope_tts_model,
        )


# 全局配置实例
# 优先级: 环境变量 > .env 文件 > 默认值
settings = AppConfig()
