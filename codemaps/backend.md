# Backend - condense-video

**Last Updated**: 2026-03-02

## Architecture

This is a Python-based backend service using FastAPI for REST API and Celery for distributed task processing.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                          │
│                      (api/main.py)                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Routers: health, tasks, videos, ws (WebSocket)                      │
│ Schemas: requests, responses, common (Pydantic)                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                      Celery Task Queue                              │
│                  (tasks/celery_app.py)                              │
├─────────────────────────────────────────────────────────────────────┤
│ Queues: video, asr, ocr, llm, tts                                   │
│ Tasks: workflows.py, asr/, ppt/, llm/, tts/, video/                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                       Service Layer                                 │
│  services/dashscope.py | services/redis_client.py                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                       Core & Utils                                  │
│  core/config.py | core/storage.py | core/progress.py                │
│  utils/ffmpeg.py | utils/text.py | utils/time.py | utils/video.py   │
└─────────────────────────────────────────────────────────────────────┘
```

## API Layer (FastAPI)

### Entry Point
**File**: [api/main.py](api/main.py)

```python
# Application lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: Init Redis, Storage
    # Shutdown: Close connections

# CORS enabled for: localhost:3000, localhost:5173, localhost:8080
```

### Routers

| Router | File | Endpoints |
|--------|------|-----------|
| Health | [api/routers/health.py](api/routers/health.py) | GET /health, /health/ready, /health/live |
| Tasks | [api/routers/tasks.py](api/routers/tasks.py) | POST/GET/DELETE /api/v1/tasks, GET /api/v1/tasks/{id}/logs |
| Videos | [api/routers/videos.py](api/routers/videos.py) | POST /api/v1/videos/process, POST /upload |
| WebSocket | [api/routers/ws.py](api/routers/ws.py) | WS /api/v1/ws/{task_id} |

### Schemas (Pydantic)

**File**: [api/schemas/](api/schemas/)

```python
# Common types
class TaskStatus(str, Enum):
    PENDING, PROCESSING, SUCCESS, FAILED, CANCELLED

class ProcessingMode(str, Enum):
    ESSENTIAL, COMPLETE

class TTSEngine(str, Enum):
    DASHSCOPE, EDGETTS

# Request models
class ProcessVideoRequest(BaseModel):
    video_url: str | None
    video_name: str
    mode: ProcessingMode
    tts_engine: TTSEngine
    voice: str
    skip_transcribe: bool
    skip_ocr: bool

# Response models
class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: float
    current_step: str | None
    result: dict | None
```

## Task Layer (Celery)

### Configuration
**File**: [tasks/celery_app.py](tasks/celery_app.py)

```python
celery_app = Celery("condense_video")
celery_app.config_from_object({
    "broker_url": settings.celery_broker_url,      # redis://redis:6379/0
    "result_backend": settings.celery_result_backend,
    "task_routes": {
        "tasks.video.*": {"queue": "video"},
        "tasks.asr.*": {"queue": "asr"},
        "tasks.ppt.*": {"queue": "ocr"},
        "tasks.llm.*": {"queue": "llm"},
        "tasks.tts.*": {"queue": "tts"},
    },
})
```

### Workflow Orchestration
**File**: [tasks/workflows.py](tasks/workflows.py)

```python
@shared_task(name="tasks.workflows.process_video")
def process_video_workflow(
    task_id: str,
    video_url: str | None,
    video_path: str | None,
    mode: str = "essential",
    tts_engine: str = "dashscope",
) -> dict:
    """完整视频处理工作流 - 同步执行"""
    # 步骤 1: 获取视频 (download/receive)
    # 步骤 2: ASR + PPT 并行
    # 步骤 3: LLM 分类
    # 步骤 4: 章节切分
    # 步骤 5: 内容总结
    # 步骤 6: TTS 文本浓缩
    # 步骤 7: TTS 生成
    # 步骤 8: 合成视频
```

### Task Modules

| Module | File | Tasks |
|--------|------|-------|
| ASR | [tasks/asr/transcribe.py](tasks/asr/transcribe.py) | transcribe_audio, convert_transcript |
| PPT | [tasks/ppt/extract.py](tasks/ppt/extract.py), [tasks/ppt/ocr.py](tasks/ppt/ocr.py) | extract_ppt_frames, ocr_slides |
| LLM | [tasks/llm/classify.py](tasks/llm/classify.py), [tasks/llm/segment.py](tasks/llm/segment.py), [tasks/llm/summarize.py](tasks/llm/summarize.py) | classify_content, segment_chapters, summarize_content, condense_for_tts |
| TTS | [tasks/tts/generate.py](tasks/tts/generate.py) | generate_tts |
| Video | [tasks/video/download.py](tasks/video/download.py), [tasks/video/audio_extract.py](tasks/video/audio_extract.py), [tasks/video/edit.py](tasks/video/edit.py) | download_video, receive_video, extract_audio_task, upload_audio_for_asr, edit_video, merge_video_with_audio |

## Service Layer

### DashScope Client
**File**: [services/dashscope.py](services/dashscope.py)

```python
class DashScopeClient:
    async def transcribe(audio_url: str) -> dict  # ASR
    async def ocr(image_path: str) -> dict        # OCR
    async def ocr_batch(image_paths: list) -> list
    async def generate_text(prompt: str) -> str    # LLM
    async def classify_batch(sentences: list) -> list
    async def tts(text: str) -> bytes             # TTS
    async def tts_batch(texts: list) -> list
```

### Redis Client
**File**: [services/redis_client.py](services/redis_client.py)

```python
def get_redis() -> redis.Redis
def set_task_status(task_id, status, progress, message)
def get_task_status(task_id) -> dict
def update_progress(task_id, step, progress, message)
def get_progress(task_id) -> dict
def save_result(task_id, result)
def get_result(task_id) -> dict
```

## Core Configuration

**File**: [core/config.py](core/config.py)

```python
class AppConfig(BaseSettings):
    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    api_reload: bool = False
    api_debug: bool = False

    # Celery 配置
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
    worker_concurrency: int = 2

    # Redis 配置
    redis_url: str = "redis://redis:6379/0"
    redis_progress_ttl: int = 604800
    redis_result_ttl: int = 2592000

    # 存储配置
    storage_backend: Literal["local", "minio", "s3", "uuguu"] = "local"
    storage_path: str = "./data"

    # DashScope 配置
    dashscope_api_key: str  # Required
    dashscope_asr_model: str = "paraformer-v2"
    dashscope_ocr_model: str = "qwen-vl-plus"
    dashscope_llm_model: str = "qwen-plus"
    dashscope_tts_model: str = "qwen3-tts-flash"

    # OCR 配置
    ocr_concurrency: int = 5
    ocr_rpm: int = 60

    # 分类配置
    classification_concurrency: int = 10
    classification_batch_size: int = 50

    # 帧提取配置
    frame_scene_threshold: float = 0.3
    frame_min_interval: int = 2
    frame_max_width: int = 1920

    # 剪辑配置
    cutting_mode_essential_delete_labels: str = "interact,chat,transition"
    cutting_mode_complete_delete_labels: str = "chat"

    # TTS 配置
    tts_engine: Literal["dashscope", "edgetts"] = "dashscope"
    tts_voice: str = "Cherry"
    tts_max_length: int = 300

    # 任务配置
    task_timeout: int = 7200
    task_max_retries: int = 3
```

## Utilities

| Module | File | Purpose |
|--------|------|---------|
| FFmpeg | [utils/ffmpeg.py](utils/ffmpeg.py) | FFmpeg command wrapper, video/audio operations |
| Text | [utils/text.py](utils/text.py) | Text processing, cleaning utilities |
| Time | [utils/time.py](utils/time.py) | Timestamp conversion, formatting |
| Video | [utils/video.py](utils/video.py) | Video metadata extraction |

## Environment Variables

```bash
# ============== API 配置 ==============
API_HOST=127.0.0.1
API_PORT=8000
API_WORKERS=1
API_RELOAD=true

# ============== Celery 配置 ==============
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
WORKER_CONCURRENCY=2

# ============== Redis 配置 ==============
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_PROGRESS_TTL=604800
REDIS_RESULT_TTL=2592000

# ============== 存储配置 ==============
STORAGE_BACKEND=uuguu
STORAGE_PATH=./data

# ============== DashScope 配置 ==============
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_ASR_MODEL=paraformer-v2
DASHSCOPE_OCR_MODEL=qwen3.5-plus
DASHSCOPE_LLM_MODEL=qwen-plus
DASHSCOPE_TTS_MODEL=qwen3-tts-flash

# ============== TTS 配置 ==============
TTS_ENGINE=dashscope
TTS_VOICE=Cherry

# ============== 剪辑配置 ==============
CUTTING_MODE_ESSENTIAL_DELETE_LABELS=interact,chat,transition
CUTTING_MODE_COMPLETE_DELETE_LABELS=chat
```

## Dependencies

### Base Dependencies
```txt
pydantic>=2.0
pydantic-settings>=2.0
redis>=5.0
httpx>=0.24
python-dotenv>=1.0
loguru>=0.7
tenacity>=8.2
```

### API Dependencies
```txt
fastapi>=0.104
uvicorn[standard]>=0.24
websockets>=12.0
celery[redis]>=5.3
flower>=2.0
prometheus-client>=0.19
```

### Worker Dependencies
```txt
celery[redis]>=5.3
opencv-python>=4.8
Pillow>=10.0
imagehash>=4.3
httpx[http2]>=0.24
edge-tts>=6.1
minio>=7.0
```

## Running the Service

```bash
# Install dependencies
pip install -e ".[api,worker]"

# Start API server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Start Celery worker
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# Start Celery beat (for scheduled tasks)
celery -A tasks.celery_app beat --loglevel=info

# Start Flower (monitoring)
celery -A tasks.celery_app flower
```

## Legacy Scripts (JavaScript)

The `scripts/` directory contains standalone Node.js scripts from the original implementation:

| Script | Purpose |
|--------|---------|
| [scripts/dashscope_transcribe.js](scripts/dashscope_transcribe.js) | ASR transcription |
| [scripts/ocr_slides.js](scripts/ocr_slides.js) | PPT OCR |
| [scripts/classify_content.js](scripts/classify_content.js) | Content classification |
| [scripts/generate_tts.js](scripts/generate_tts.js) | TTS generation |
| [scripts/compose_video.js](scripts/compose_video.js) | Video composition |

These are maintained for backward compatibility but are superseded by the Python/Celery implementation.
