# 配置管理 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. 设计原则

**所有配置均通过 `.env` 文件管理，无需修改代码**

## 2. .env 文件完整配置

```bash
# ============== API 配置 ==============
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1
API_RELOAD=false

# ============== Celery 配置 ==============
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
WORKER_CONCURRENCY=2
WORKER_PREFETCH_MULTIPLIER=4

# ============== Redis 配置 ==============
REDIS_URL=redis://redis:6379/0
REDIS_PROGRESS_TTL=604800
REDIS_RESULT_TTL=2592000

# ============== 存储配置 ==============
STORAGE_BACKEND=local
STORAGE_PATH=./data
# MinIO 配置 (当 STORAGE_BACKEND=minio 时使用)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=condense-video
MINIO_SECURE=false
# S3 配置 (当 STORAGE_BACKEND=s3 时使用)
S3_ENDPOINT=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_BUCKET=
S3_REGION=

# ============== DashScope 配置 ==============
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_ASR_MODEL=paraformer-v2
DASHSCOPE_OCR_MODEL=qwen-vl-plus
DASHSCOPE_LLM_MODEL=qwen-plus
DASHSCOPE_TTS_MODEL=qwen3-tts-flash

# ============== OCR 配置 ==============
OCR_PROVIDER=dashscope
OCR_MODEL=qwen-vl-plus
OCR_CONCURRENCY=5
OCR_RPM=60
OCR_RETRY_TIMES=3
OCR_RETRY_DELAY=1000

# ============== 内容分类配置 ==============
CLASSIFICATION_PROVIDER=dashscope
CLASSIFICATION_MODEL=qwen-plus
CLASSIFICATION_CONCURRENCY=10
CLASSIFICATION_BATCH_SIZE=50

# ============== 帧提取配置 ==============
FRAME_SCENE_THRESHOLD=0.3
FRAME_MIN_INTERVAL=2
FRAME_MAX_WIDTH=1920

# ============== 剪辑配置 ==============
CUTTING_MODE_ESSENTIAL_DELETE_LABELS=interact,chat,transition
CUTTING_MODE_COMPLETE_DELETE_LABELS=chat
CUTTING_BUFFER_MS=50
CUTTING_CROSSFADE_MS=30

# ============== TTS 配置 ==============
TTS_ENGINE=dashscope
TTS_VOICE=Cherry
TTS_MAX_LENGTH=300
TTS_CONCURRENCY=3

# ============== Edge TTS 配置 (当 TTS_ENGINE=edgetts 时) ================
EDGETTS_VOICE=zh-CN-XiaoxiaoNeural
EDGETTS_RATE=0
EDGETTS_VOLUME=0

# ============== 任务配置 ==============
TASK_TIMEOUT=7200
TASK_MAX_RETRIES=3
```

## 3. 原配置 vs 新配置对比

### 3.1 原 JS 配置 (config.json)

```json
{
  "name": "videocut:精要提炼",
  "version": "1.0.0",

  "ocr": {
    "provider": "dashscope",
    "model": "qwen3.5-plus",
    "concurrency": 5,
    "rpm": 60,
    "retryTimes": 3,
    "retryDelay": 1000
  },

  "classification": {
    "provider": "dashscope",
    "model": "qwen-plus",
    "concurrency": 10,
    "batchSize": 50
  },

  "frameExtraction": {
    "sceneThreshold": 0.3,
    "minInterval": 2,
    "maxWidth": 1920
  },

  "cutting": {
    "modes": {
      "essential": {
        "description": "精要版 - 仅保留核心知识",
        "deleteLabels": ["interact", "chat", "transition"]
      },
      "complete": {
        "description": "完整版 - 保留核心+解释",
        "deleteLabels": ["chat"]
      }
    },
    "bufferMs": 50,
    "crossfadeMs": 30
  }
}
```

### 3.2 新 Python 配置

| 原配置路径 | 新配置环境变量 | 默认值 |
|------------|----------------|--------|
| `ocr.provider` | `OCR_PROVIDER` | dashscope |
| `ocr.model` | `OCR_MODEL` | qwen-vl-plus |
| `ocr.concurrency` | `OCR_CONCURRENCY` | 5 |
| `ocr.rpm` | `OCR_RPM` | 60 |
| `ocr.retryTimes` | `OCR_RETRY_TIMES` | 3 |
| `ocr.retryDelay` | `OCR_RETRY_DELAY` | 1000 |
| `classification.model` | `CLASSIFICATION_MODEL` | qwen-plus |
| `classification.concurrency` | `CLASSIFICATION_CONCURRENCY` | 10 |
| `classification.batchSize` | `CLASSIFICATION_BATCH_SIZE` | 50 |
| `frameExtraction.sceneThreshold` | `FRAME_SCENE_THRESHOLD` | 0.3 |
| `frameExtraction.minInterval` | `FRAME_MIN_INTERVAL` | 2 |
| `frameExtraction.maxWidth` | `FRAME_MAX_WIDTH` | 1920 |
| `cutting.modes.essential.deleteLabels` | `CUTTING_MODE_ESSENTIAL_DELETE_LABELS` | interact,chat,transition |
| `cutting.modes.complete.deleteLabels` | `CUTTING_MODE_COMPLETE_DELETE_LABELS` | chat |
| `cutting.bufferMs` | `CUTTING_BUFFER_MS` | 50 |
| `cutting.crossfadeMs` | `CUTTING_CROSSFADE_MS` | 30 |

### 3.3 新增配置项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `API_HOST/PORT` | API 服务地址 | 0.0.0.0:8000 |
| `CELERY_BROKER_URL` | Celery 消息队列 | redis://redis:6379/0 |
| `STORAGE_BACKEND` | 存储后端选择 | local |
| `DASHSCOPE_API_KEY` | DashScope API 密钥 | (必需) |
| `TTS_ENGINE` | TTS 引擎选择 | dashscope |
| `TTS_VOICE` | TTS 音色 | Cherry |
| `TASK_TIMEOUT` | 任务超时时间 (秒) | 7200 |

## 4. 配置类设计

```python
# core/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Literal


class DashScopeConfig(BaseModel):
    """DashScope 配置"""
    api_key: str
    asr_model: str = "paraformer-v2"
    ocr_model: str = "qwen-vl-plus"
    llm_model: str = "qwen-plus"
    tts_model: str = "qwen3-tts-flash"
    rpm: int = 60
    retry_times: int = 3
    retry_delay: int = 1000


class AppConfig(BaseSettings):
    """应用配置 - 全部支持 .env 覆盖"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="allow"
    )

    # ============== API 配置 ==============
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_workers: int = Field(default=1, alias="API_WORKERS")
    api_reload: bool = Field(default=False, alias="API_RELOAD")

    # ============== Celery 配置 ==============
    celery_broker_url: str = Field(default="redis://redis:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/0", alias="CELERY_RESULT_BACKEND")
    worker_concurrency: int = Field(default=2, alias="WORKER_CONCURRENCY")
    worker_prefetch_multiplier: int = Field(default=4, alias="WORKER_PREFETCH_MULTIPLIER")

    # ============== Redis 配置 ==============
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    redis_progress_ttl: int = Field(default=604800, alias="REDIS_PROGRESS_TTL")  # 7天
    redis_result_ttl: int = Field(default=2592000, alias="REDIS_RESULT_TTL")  # 30天

    # ============== 存储配置 ==============
    storage_backend: Literal["local", "minio", "s3"] = Field(default="local", alias="STORAGE_BACKEND")
    storage_path: str = Field(default="./data", alias="STORAGE_PATH")

    # MinIO
    minio_endpoint: str | None = Field(default=None, alias="MINIO_ENDPOINT")
    minio_access_key: str | None = Field(default=None, alias="MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(default=None, alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="condense-video", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    # S3
    s3_endpoint: str | None = Field(default=None, alias="S3_ENDPOINT")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET")
    s3_region: str | None = Field(default=None, alias="S3_REGION")

    # ============== DashScope 配置 ==============
    dashscope_api_key: str = Field(..., alias="DASHSCOPE_API_KEY")
    dashscope_asr_model: str = Field(default="paraformer-v2", alias="DASHSCOPE_ASR_MODEL")
    dashscope_ocr_model: str = Field(default="qwen-vl-plus", alias="DASHSCOPE_OCR_MODEL")
    dashscope_llm_model: str = Field(default="qwen-plus", alias="DASHSCOPE_LLM_MODEL")
    dashscope_tts_model: str = Field(default="qwen3-tts-flash", alias="DASHSCOPE_TTS_MODEL")

    # ============== OCR 配置 ==============
    ocr_provider: str = Field(default="dashscope", alias="OCR_PROVIDER")
    ocr_model: str = Field(default="qwen-vl-plus", alias="OCR_MODEL")
    ocr_concurrency: int = Field(default=5, alias="OCR_CONCURRENCY")
    ocr_rpm: int = Field(default=60, alias="OCR_RPM")
    ocr_retry_times: int = Field(default=3, alias="OCR_RETRY_TIMES")
    ocr_retry_delay: int = Field(default=1000, alias="OCR_RETRY_DELAY")

    # ============== 分类配置 ==============
    classification_provider: str = Field(default="dashscope", alias="CLASSIFICATION_PROVIDER")
    classification_model: str = Field(default="qwen-plus", alias="CLASSIFICATION_MODEL")
    classification_concurrency: int = Field(default=10, alias="CLASSIFICATION_CONCURRENCY")
    classification_batch_size: int = Field(default=50, alias="CLASSIFICATION_BATCH_SIZE")

    # ============== 帧提取配置 ==============
    frame_scene_threshold: float = Field(default=0.3, alias="FRAME_SCENE_THRESHOLD")
    frame_min_interval: int = Field(default=2, alias="FRAME_MIN_INTERVAL")
    frame_max_width: int = Field(default=1920, alias="FRAME_MAX_WIDTH")

    # ============== 剪辑配置 ==============
    cutting_mode_essential_delete_labels: str = Field(
        default="interact,chat,transition",
        alias="CUTTING_MODE_ESSENTIAL_DELETE_LABELS"
    )
    cutting_mode_complete_delete_labels: str = Field(
        default="chat",
        alias="CUTTING_MODE_COMPLETE_DELETE_LABELS"
    )
    cutting_buffer_ms: int = Field(default=50, alias="CUTTING_BUFFER_MS")
    cutting_crossfade_ms: int = Field(default=30, alias="CUTTING_CROSSFADE_MS")

    # ============== TTS 配置 ==============
    tts_engine: Literal["dashscope", "edgetts"] = Field(default="dashscope", alias="TTS_ENGINE")
    tts_voice: str = Field(default="Cherry", alias="TTS_VOICE")
    tts_max_length: int = Field(default=300, alias="TTS_MAX_LENGTH")
    tts_concurrency: int = Field(default=3, alias="TTS_CONCURRENCY")

    # Edge TTS 特定配置
    edgetts_voice: str = Field(default="zh-CN-XiaoxiaoNeural", alias="EDGETTS_VOICE")
    edgetts_rate: int = Field(default=0, alias="EDGETTS_RATE")
    edgetts_volume: int = Field(default=0, alias="EDGETTS_VOLUME")

    # ============== 任务配置 ==============
    task_timeout: int = Field(default=7200, alias="TASK_TIMEOUT")  # 2小时
    task_max_retries: int = Field(default=3, alias="TASK_MAX_RETRIES")

    @property
    def cutting_modes(self) -> dict:
        """解析剪辑模式配置"""
        return {
            "essential": {
                "description": "精要版 - 仅保留核心知识",
                "delete_labels": self.cutting_mode_essential_delete_labels.split(",")
            },
            "complete": {
                "description": "完整版 - 保留核心+解释",
                "delete_labels": self.cutting_mode_complete_delete_labels.split(",")
            }
        }

    @property
    def dashscope(self) -> DashScopeConfig:
        """DashScope 配置对象"""
        return DashScopeConfig(
            api_key=self.dashscope_api_key,
            asr_model=self.dashscope_asr_model,
            ocr_model=self.dashscope_ocr_model,
            llm_model=self.dashscope_llm_model,
            tts_model=self.dashscope_tts_model
        )


# 全局配置实例
settings = AppConfig()
```

## 5. 配置使用示例

```python
# 在代码中使用配置

from core.config import settings

# 获取 DashScope API Key
api_key = settings.dashscope_api_key

# 获取 OCR 并发数
ocr_concurrency = settings.ocr_concurrency

# 获取剪辑模式
cutting_modes = settings.cutting_modes
# => {
#      "essential": {"delete_labels": ["interact", "chat", "transition"]},
#      "complete": {"delete_labels": ["chat"]}
#    }

# 获取存储后端
if settings.storage_backend == "minio":
    endpoint = settings.minio_endpoint
```

## 6. 分类标签配置

原 JS 配置中的 `labels` 部分迁移到规则文件：

```python
# 从规则文件读取 (core/rules/classification.py)
LABELS = {
    "core": {
        "name": "核心知识",
        "description": "定义、公式、定理、重要概念",
        "action": "保留"
    },
    "explain": {
        "name": "解释说明",
        "description": "对核心内容的解释、举例",
        "action": "可选"
    },
    "interact": {
        "name": "课堂互动",
        "description": "师生互动、提问、回答",
        "action": "建议删除"
    },
    "chat": {
        "name": "闲聊跑题",
        "description": "与课程无关的内容",
        "action": "删除"
    },
    "transition": {
        "name": "过渡语",
        "description": "承上启下的过渡语句",
        "action": "可删除"
    }
}
```
