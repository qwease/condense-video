# 组件设计 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. 项目目录结构

```
condense-video-backend/
├── api/                        # FastAPI 应用
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── dependencies.py         # 依赖注入
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── videos.py           # 视频处理 API
│   │   ├── tasks.py            # 任务查询 API
│   │   ├── health.py           # 健康检查 API
│   │   └── ws.py               # WebSocket 路由
│   ├── models/
│   │   ├── __init__.py
│   │   ├── task.py             # 任务数据模型
│   │   └── video.py            # 视频数据模型
│   └── schemas/
│       ├── __init__.py
│       ├── task.py             # API 请求/响应 Schema
│       └── video.py
│
├── tasks/                      # Celery 任务
│   ├── __init__.py
│   ├── celery_app.py           # Celery 配置
│   ├── workflows.py            # 工作流编排 (chain/group)
│   ├── video/
│   │   ├── __init__.py
│   │   ├── download.py         # 视频下载/接收
│   │   ├── audio_extract.py    # 音频提取
│   │   └── edit.py             # 视频剪辑合成
│   ├── asr/
│   │   ├── __init__.py
│   │   └── transcribe.py       # 语音转录
│   ├── ppt/
│   │   ├── __init__.py
│   │   ├── extract.py          # PPT 关键帧提取
│   │   └── ocr.py              # OCR 识别
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── classify.py         # 内容分类
│   │   ├── segment.py          # 章节切分
│   │   └── summarize.py        # 内容总结
│   └── tts/
│       ├── __init__.py
│       └── generate.py         # TTS 生成
│
├── core/                       # 核心业务逻辑
│   ├── __init__.py
│   ├── config.py               # 配置管理
│   ├── storage.py              # 存储抽象 (MinIO/S3/本地)
│   ├── progress.py             # 进度推送 (Redis Pub/Sub)
│   ├── exceptions.py           # 自定义异常
│   ├── logging.py              # 日志配置
│   ├── metrics.py              # Prometheus 指标
│   └── rules/                  # 分类规则 (从 规则/ 迁移)
│       ├── __init__.py
│       ├── classification.py   # 内容分类规则
│       ├── structure.py        # 结构提取规则
│       ├── summary.py          # 总结生成模板
│       └── ppt.py              # PPT 分析规则
│
├── services/                   # 外部服务客户端
│   ├── __init__.py
│   ├── dashscope.py            # DashScope API (ASR/OCR/LLM/TTS)
│   ├── redis_client.py         # Redis 客户端
│   └── storage.py              # 对象存储客户端
│
├── utils/                      # 工具函数
│   ├── __init__.py
│   ├── ffmpeg.py               # FFmpeg 封装
│   ├── video.py                # 视频处理工具
│   └── time.py                 # 时间处理
│
├── docker/
│   ├── Dockerfile.api          # API 容器
│   ├── Dockerfile.worker       # Worker 容器
│   └── docker-compose.yml      # 容器编排
│
├── tests/                      # 测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   ├── test_tasks/
│   └── test_workflows.py
│
├── requirements/
│   ├── base.txt
│   ├── api.txt
│   └── worker.txt
│
├── .env.example
├── pyproject.toml
└── README.md
```

## 2. 核心组件说明

### 2.1 API 层 (api/)

**main.py** - FastAPI 应用入口
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import videos, tasks, health, ws
from core.logging import setup_logging

# 配置日志
logger = setup_logging()

# 创建应用
app = FastAPI(
    title="Condense Video API",
    description="课程视频内容提炼服务",
    version="2.0.0"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(videos.router)
app.include_router(tasks.router)
app.include_router(health.router)
app.include_router(ws.router)

# 启动事件
@app.on_event("startup")
async def startup_event():
    logger.info("Condense Video API starting...")
```

**dependencies.py** - 依赖注入
```python
from fastapi import Header, HTTPException
from core.config import settings

async def verify_api_key(x_api_key: str = Header(...)):
    """验证 API Key (可选)"""
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key
```

### 2.2 任务层 (tasks/)

**celery_app.py** - Celery 配置
```python
from celery import Celery
from core.config import settings

celery_app = Celery("condense_video")
celery_app.config_from_object({
    "broker_url": settings.celery_broker_url,
    "result_backend": settings.celery_result_backend,
    "task_track_started": True,
    "task_time_limit": settings.task_timeout,
    "task_acks_late": True,
    "worker_prefetch_multiplier": settings.worker_prefetch_multiplier,
    "task_routes": {
        "tasks.video.*": {"queue": "video"},
        "tasks.asr.transcribe": {"queue": "asr"},
        "tasks.ppt.ocr": {"queue": "ocr"},
        "tasks.llm.*": {"queue": "llm"},
        "tasks.tts.generate": {"queue": "tts"},
    }
})
```

**workflows.py** - 工作流编排
```python
from celery import chain, group
from tasks.video import audio_extract, ppt_extract, edit
from tasks.asr import transcribe
from tasks.ppt import ocr
from tasks.llm import classify, segment, summarize
from tasks.tts import generate

def process_video_workflow(video_path: str, options: dict):
    """
    视频处理工作流 - 优化版 (并行 ASR + OCR)
    """
    # 并行阶段 1: 音频提取 + PPT 提取
    parallel_extract = group(
        audio_extract.s(video_path),
        ppt_extract.s(video_path)
    )

    # 并行阶段 2: ASR 转录 + OCR 识别
    parallel_process = group(
        transcribe.s(),
        ocr.s()
    )

    # 串行阶段
    sequential_process = chain(
        classify.s(),           # 融合 ASR + OCR 结果
        segment.s(),
        summarize.s(),
        generate.s(),
        edit.s(video_path)
    )

    return chain(
        parallel_extract,
        parallel_process,
        sequential_process
    )
```

### 2.3 核心层 (core/)

**config.py** - 配置管理 (详见 config.md)

**progress.py** - 进度推送
```python
import json
from datetime import datetime
from services.redis_client import redis

def update_progress(task_id: str, step: str, progress: float, message: str, data: dict = None):
    """更新任务进度"""
    key = f"task-progress:{task_id}"
    payload = {
        "step": step,
        "progress": progress,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now().isoformat()
    }
    # 存储最新状态
    redis.set(f"{key}:latest", json.dumps(payload), ex=86400)
    # 发布到频道 (WebSocket 订阅)
    redis.publish(f"progress:{task_id}", json.dumps(payload))
```

**storage.py** - 存储抽象
```python
from abc import ABC, abstractmethod
from core.config import settings

class StorageBackend(ABC):
    """存储后端抽象"""

    @abstractmethod
    async def upload(self, file_path: str, object_name: str) -> str:
        """上传文件，返回 URL"""
        pass

    @abstractmethod
    async def download(self, object_name: str, local_path: str):
        """下载文件"""
        pass

    @abstractmethod
    async def get_url(self, object_name: str) -> str:
        """获取文件 URL"""
        pass


class LocalStorage(StorageBackend):
    """本地存储"""
    async def upload(self, file_path: str, object_name: str) -> str:
        # 复制到存储目录
        return f"http://localhost:8000/static/{object_name}"


class MinIOStorage(StorageBackend):
    """MinIO 存储"""
    def __init__(self):
        from minio import Minio
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure
        )

    async def upload(self, file_path: str, object_name: str) -> str:
        self.client.fput_object(settings.minio_bucket, object_name, file_path)
        return f"{settings.minio_endpoint}/{settings.minio_bucket}/{object_name}"


def get_storage() -> StorageBackend:
    """获取存储后端"""
    backends = {
        "local": LocalStorage,
        "minio": MinIOStorage,
    }
    return backends[settings.storage_backend]()
```

### 2.4 服务层 (services/)

**dashscope.py** - DashScope API 客户端
```python
import httpx
from core.config import settings

class DashScopeClient:
    """DashScope API 客户端"""

    def __init__(self):
        self.api_key = settings.dashscope_api_key
        self.base_url = "https://dashscope.aliyuncs.com/api/v1"

    async def transcribe(self, audio_url: str) -> dict:
        """ASR 转录"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/services/asr/transcription",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": settings.dashscope_asr_model,
                    "input": {"urls": [audio_url]}
                }
            )
            return response.json()

    async def ocr(self, image_url: str) -> dict:
        """OCR 识别"""
        pass

    async def classify(self, sentences: list, ppt_context: list) -> list:
        """内容分类"""
        pass

    async def tts(self, text: str, voice: str) -> bytes:
        """TTS 生成"""
        pass
```

### 2.5 工具层 (utils/)

**ffmpeg.py** - FFmpeg 封装
```python
import subprocess
from pathlib import Path

async def extract_audio(video_path: str, output_path: str) -> str:
    """提取音频"""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "libmp3lame",
        "-y", output_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()
    return output_path

async def extract_frames(video_path: str, output_dir: str, threshold: float = 0.3):
    """提取关键帧"""
    output_pattern = str(Path(output_dir) / "frame_%05d.jpg")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})'",
        "-vsync", "vfr",
        "-qscale:v", "2",
        "-y", output_pattern
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()
```

## 3. 数据模型

### 3.1 任务状态

```python
# api/models/task.py

from enum import Enum
from pydantic import BaseModel
from typing import Optional

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStep(str, Enum):
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


class Task(BaseModel):
    """任务模型"""
    task_id: str
    status: TaskStatus
    progress: float = 0.0
    current_step: Optional[TaskStep] = None
    message: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
```

### 3.2 分类标签

```python
# core/rules/classification.py

class ClassificationLabel(str, Enum):
    CORE = "core"           # 必留
    EXPLAIN = "explain"     # 可选
    INTERACT = "interact"   # 建议删
    CHAT = "chat"           # 必删
    TRANSITION = "transition"  # 可删


LABEL_ACTIONS = {
    ClassificationLabel.CORE: "keep",
    ClassificationLabel.EXPLAIN: "optional",
    ClassificationLabel.INTERACT: "delete",
    ClassificationLabel.CHAT: "delete",
    ClassificationLabel.TRANSITION: "delete",
}
```

## 4. 步骤权重 (进度计算)

```python
# tasks/workflows.py

STEP_WEIGHTS = {
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

def calculate_progress(completed_steps: list[TaskStep], current_step: TaskStep, step_progress: float) -> float:
    """计算总体进度"""
    # 已完成步骤的权重和
    completed_weight = sum(STEP_WEIGHTS[s] for s in completed_steps)
    # 当前步骤的权重
    current_weight = STEP_WEIGHTS[current_step]
    # 总进度 = 已完成 + 当前步骤进度
    return completed_weight + (current_weight * step_progress)
```
