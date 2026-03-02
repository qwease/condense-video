# Architecture - condense-video

**Last Updated**: 2026-03-02

## Overview

Course video content extraction service (课程视频内容提炼). Combines speech transcription and PPT OCR analysis to extract core knowledge from long videos, filtering out classroom interaction and casual content, generating condensed versions and course outlines.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11+ | Application runtime |
| API Framework | FastAPI 0.104+ | REST API & WebSocket |
| Task Queue | Celery 5.3+ | Distributed async task processing |
| Broker | Redis | Message queue & result backend |
| State Store | Redis | Task progress & result caching |
| ASR | DashScope paraformer-v2 | Speech recognition |
| OCR | DashScope qwen-vl-plus | PPT text extraction |
| LLM | DashScope qwen-plus | Content classification |
| TTS | DashScope qwen3-tts-flash / Edge TTS | Voice generation |
| Video | FFmpeg | Audio extraction, frame detection, editing |
| Testing | pytest, pytest-cov, pytest-asyncio | Unit & integration tests |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Client Layer                             │
│              (Web UI, CLI, Mobile App, Third-party)                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP/WebSocket
┌────────────────────────────┴────────────────────────────────────────┐
│                         API Layer (FastAPI)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ /health  │  │ /tasks   │  │ /videos  │  │ /ws (progress)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                      Task Queue (Celery)                             │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Worker Processes                             │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │ │
│  │  │  video  │ │   asr   │ │   ppt   │ │   llm   │ │   tts   │ │ │
│  │  │  queue  │ │  queue  │ │  queue  │ │  queue  │ │  queue  │ │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │ │
│  └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                       Service Layer                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ DashScope    │  │ Redis Client │  │ Storage      │              │
│  │ Client       │  │              │  │ (Local/S3)   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
condense-video/
├── api/                   # FastAPI application
│   ├── main.py           # Application entry point
│   ├── routers/          # API route handlers
│   │   ├── health.py     # Health check endpoints
│   │   ├── tasks.py      # Task management endpoints
│   │   ├── videos.py     # Video processing endpoints
│   │   └── ws.py         # WebSocket progress updates
│   └── schemas/          # Pydantic schemas
│       ├── common.py     # Shared enums/types
│       ├── requests.py   # Request models
│       └── responses.py  # Response models
│
├── tasks/                 # Celery tasks
│   ├── celery_app.py     # Celery application configuration
│   ├── workflows.py      # Orchestration of task chains
│   ├── asr/              # ASR transcription tasks
│   ├── ppt/              # PPT extraction & OCR tasks
│   ├── llm/              # LLM classification tasks
│   ├── tts/              # TTS generation tasks
│   └── video/            # Video processing tasks
│
├── services/              # External service clients
│   ├── dashscope.py      # DashScope API client
│   └── redis_client.py   # Redis state management
│
├── core/                  # Core business logic
│   ├── config.py         # Configuration management (pydantic-settings)
│   ├── exceptions.py     # Custom exceptions
│   ├── logging.py        # Logging configuration
│   ├── progress.py       # Progress tracking
│   ├── storage.py        # Storage abstraction layer
│   └── rules/            # Classification/extraction rules
│
├── utils/                 # Utility functions
│   ├── ffmpeg.py         # FFmpeg wrapper
│   ├── text.py           # Text processing utilities
│   ├── time.py           # Time/timestamp utilities
│   └── video.py          # Video processing utilities
│
├── tests/                 # Test suite
│   ├── conftest.py       # Pytest fixtures
│   ├── test_api/         # API tests
│   ├── test_tasks/       # Task tests
│   └── test_services/    # Service tests
│
├── scripts/               # Standalone JavaScript scripts (legacy)
│   ├── dashscope_transcribe.js
│   ├── ocr_slides.js
│   ├── classify_content.js
│   └── ...
│
├── pyproject.toml         # Project configuration
├── .env                   # Environment variables
└── requirements/          # Python dependencies
    ├── base.txt
    ├── api.txt
    └── worker.txt
```

## Core Workflows

### 精要提炼 (Essential Extraction)

Primary workflow for extracting core knowledge from course videos:

```
Video Input (URL or file upload)
    ↓
[Video Download/Receive]
    ↓
┌─────────────┬─────────────┐
│   ASR Branch │   PPT Branch │  (Parallel execution)
│             │             │
│ [1_转录]     │ [5_PPT]      │
│ Extract     │ Extract      │
│ Audio       │ Frames       │
│    ↓        │    ↓         │
│ Upload      │              │
│ for ASR     │              │
│    ↓        │    ↓         │
│ ASR         │ OCR          │
│ Transcribe  │ Slides       │
│    ↓        │    ↓         │
│ Convert     │ Structure    │
└─────────────┴─────────────┘
        ↓
[2_文稿] Content Classification (AI: speech + PPT fusion)
        ↓
Chapter Segmentation (based on PPT switches)
        ↓
Content Summarization (key points extraction)
        ↓
[3_音频] TTS Text Condensation
        ↓
TTS Generation (DashScope / Edge TTS)
        ↓
[4_视频] Smart Video Editing (remove non-core segments)
        ↓
Video + TTS Audio Merge
        ↓
Output: Condensed video + course outline + summary
```

## Data Flow

```
Input: video.mp4 or video URL
    ├─→ Video Download/Receive → local video file
    ├─→ Audio Extraction → ASR → transcript.json → sentences.txt
    ├─→ Frame Extraction → images/ → OCR → ocr_result.json
    └─→ Metadata (duration, fps)

sentences.txt + ocr_result.json
    ↓
AI Classification (DashScope LLM)
    ↓
classification.json (with labels: core/explain/interact/chat/transition)

classification.json + ocr_result.json
    ↓
Chapter Detection + Summarization
    ↓
outline.md + summary.md + condensed.json

condensed.json → TTS → audio_timing.json + tts_audio.mp3

frames_info.json + audio_timing.json + original video
    ↓
Video Editing (FFmpeg)
    ↓
condensed_course.mp4 (final output)
```

## API Endpoints

### Health Check
- `GET /health` - Service health status
- `GET /health/ready` - Readiness check
- `GET /health/live` - Liveness check

### Task Management
- `POST /api/v1/tasks` - Submit new processing task
- `GET /api/v1/tasks/{task_id}` - Query task status
- `DELETE /api/v1/tasks/{task_id}` - Cancel task
- `GET /api/v1/tasks/{task_id}/logs` - Get task logs
- `GET /api/v1/tasks/{task_id}/progress` - Get real-time progress

### Video Processing
- `POST /api/v1/videos/process` - Process video from URL
- `POST /api/v1/videos/upload` - Upload and process video file
- `GET /api/v1/videos/{video_id}` - Get video result
- `GET /api/v1/videos/{video_id}/download` - Download processed video

### WebSocket
- `WS /api/v1/ws/{task_id}` - Real-time progress updates

## Celery Task Queues

| Queue | Purpose | Tasks |
|-------|---------|-------|
| video | Video processing | download, receive, edit, merge |
| asr | Speech recognition | extract_audio, transcribe, convert |
| ocr | PPT analysis | extract_frames, ocr_slides |
| llm | AI analysis | classify, segment, summarize |
| tts | Voice generation | generate_tts |

## Classification Labels

| Label | Description | Action |
|-------|-------------|--------|
| core | Core knowledge (definitions, formulas) | Keep |
| explain | Explanations, examples | Optional |
| interact | Classroom interaction | Delete |
| chat | Off-topic chat | Delete |
| transition | Transition phrases | Delete |

## Processing Modes

| Mode | Description | Deleted Labels |
|------|-------------|----------------|
| essential | 精要版 - Core knowledge only | interact, chat, transition |
| complete | 完整版 - Core + explanations | chat |

## Configuration

All configuration managed via environment variables in `.env`:

- `API_HOST`, `API_PORT` - API server settings
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` - Celery broker
- `REDIS_URL` - Redis connection
- `DASHSCOPE_API_KEY` - DashScope API key (required)
- `STORAGE_BACKEND` - Storage type (local/minio/s3/uuguu)
- `TTS_ENGINE` - TTS engine (dashscope/edgetts)
- Plus many more - see [core/config.py](core/config.py)
