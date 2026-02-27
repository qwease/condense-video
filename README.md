# Condense Video Python Backend

> 课程视频内容提炼服务 - 结合语音转录和 PPT OCR 分析，从长视频中提取核心知识

## 功能特性

- **视频处理**: 支持从 URL 下载或直接上传视频文件
- **语音转录**: 使用阿里云 DashScope ASR 进行高精度语音识别
- **PPT 分析**: FFmpeg 场景检测 + OpenCV 感知哈希提取关键帧，DashScope VL OCR 识别
- **AI 分类**: 融合语音和 PPT 信息，智能分类内容 (核心/解释/互动/闲聊/过渡)
- **章节切分**: 基于 PPT 切换自动切分课程章节
- **内容总结**: LLM 生成课程总结和核心要点
- **TTS 合成**: 支持阿里云 CosyVoice 和微软 Edge TTS 生成配音
- **视频剪辑**: 根据分类结果自动剪辑浓缩视频
- **实时进度**: WebSocket 推送任务处理进度

## 架构设计

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  FastAPI    │────▶│   Redis     │◀────│   Celery    │
│  (API 层)   │     │  (状态存储)  │     │  (任务队列)  │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       │                   ▼                   ▼
       │            ┌─────────────┐     ┌─────────────┐
       │            │  Pub/Sub    │     │   Workers   │
       │            │ (进度推送)   │     │  (处理任务)  │
       │            └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  WebSocket  │     │   MinIO     │     │ DashScope   │
│ (实时通信)   │     │  (存储)     │     │   (AI)      │
└─────────────┘     └─────────────┘     └─────────────┘
```

## 快速开始

### 环境要求

- Python 3.10+
- Redis 7+
- FFmpeg 4.4+
- (可选) MinIO 或 S3 兼容存储

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd python-backend

# 安装依赖
pip install -r requirements/all.txt

# 复制配置文件
cp .env.example .env

# 编辑配置，设置 API 密钥
# DASHSCOPE_API_KEY=sk-xxxxx
```

### 配置

所有配置通过 `.env` 文件管理，无需修改代码：

```bash
# ============== API 配置 ==============
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1
API_RELOAD=false
API_DEBUG=false

# ============== Redis 配置 ==============
REDIS_URL=redis://localhost:6379/0

# ============== Celery 配置 ==============
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
WORKER_CONCURRENCY=2

# ============== DashScope API ==============
DASHSCOPE_API_KEY=sk-xxxxx  # 必需

# ============== 存储配置 ==============
STORAGE_BACKEND=local       # local, minio, s3
STORAGE_PATH=./data

# MinIO (可选)
# MINIO_ENDPOINT=localhost:9000
# MINIO_ACCESS_KEY=minioadmin
# MINIO_SECRET_KEY=minioadmin
# MINIO_BUCKET=condense-video

# ============== OCR 配置 ==============
OCR_MODEL=qwen-vl-plus
OCR_CONCURRENCY=5

# ============== 分类配置 ==============
CLASSIFICATION_MODEL=qwen-plus
CLASSIFICATION_CONCURRENCY=10

# ============== TTS 配置 ==============
TTS_ENGINE=dashscope       # dashscope, edgetts
TTS_VOICE=Cherry
TTS_MAX_LENGTH=300
```

### 启动服务

```bash
# 1. 启动 Redis
docker run -d -p 6379:6379 redis:7-alpine

# 2. 启动 Celery Worker
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# 3. 启动 API 服务
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 或使用 Docker Compose (一键启动)
docker-compose up -d
```

### 验证安装

访问 `http://localhost:8000/docs` 查看 API 文档。

运行健康检查：
```bash
curl http://localhost:8000/health
```

## API 使用

### 提交视频处理任务

```bash
# 方式 1: 提供 URL
curl -X POST "http://localhost:8000/api/v1/videos/process" \
  -F "video_url=https://example.com/video.mp4" \
  -F "video_name=lecture_01" \
  -F "mode=essential" \
  -F "tts_engine=dashscope" \
  -F "voice=Cherry"

# 方式 2: 上传文件
curl -X POST "http://localhost:8000/api/v1/videos/process" \
  -F "video_file=@video.mp4" \
  -F "mode=essential"
```

### 查询任务状态

```bash
curl "http://localhost:8000/api/v1/tasks/{task_id}"
```

### WebSocket 实时进度

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/tasks/${taskId}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`[${data.type}] ${data.progress * 100}%: ${data.message}`);
};
```

## 处理模式

### Essential (精要版)
仅保留核心知识内容，删除互动、闲聊、过渡部分。

**删除标签**: `interact`, `chat`, `transition`

### Complete (完整版)
保留核心和解释内容，仅删除闲聊。

**删除标签**: `chat`

## 输出文件结构

```
output/
└── YYYY-MM-DD_视频名/
    └── 精要提炼/
        └── steps/
            ├── 1_转录/
            │   ├── audio.mp3          # 提取的音频
            │   └── transcript.json     # ASR 转录结果
            ├── 2_文稿/
            │   ├── sentences.txt       # 分句文本
            │   ├── classification.json # AI 分类结果
            │   ├── classification.md   # 分类报告
            │   ├── outline.json        # 章节大纲
            │   ├── outline.md          # 可读大纲
            │   ├── summary.md          # 课程总结
            │   ├── key_points.md       # 核心要点
            │   └── condensed.txt       # 浓缩文本
            ├── 3_音频/
            │   ├── segment_*.mp3       # TTS 片段
            │   ├── audio_timing.json   # 时间信息
            │   └── tts_audio.mp3       # 合成音频
            ├── 4_视频/
            │   └── condensed_course.mp4 # 浓缩视频
            └── 5_PPT/
                ├── images/             # 关键帧
                └── ocr_result.json     # OCR 结果
```

## 开发

### 项目结构

```
python-backend/
├── api/                 # FastAPI 应用
│   ├── main.py          # 应用入口
│   ├── routers/         # API 路由
│   └── schemas/         # Pydantic 模型
├── core/                # 核心组件
│   ├── config.py        # 配置管理
│   ├── exceptions.py    # 自定义异常
│   ├── logging.py       # 日志配置
│   ├── progress.py      # 进度定义
│   └── storage.py       # 存储抽象
├── services/            # 外部服务
│   ├── dashscope.py     # DashScope 客户端
│   └── redis_client.py  # Redis 客户端
├── tasks/               # Celery 任务
│   ├── celery_app.py    # Celery 配置
│   ├── video/           # 视频处理任务
│   ├── asr/             # ASR 任务
│   ├── ppt/             # PPT 任务
│   ├── llm/             # LLM 任务
│   ├── tts/             # TTS 任务
│   └── workflows.py     # 工作流编排
├── utils/               # 工具函数
│   ├── ffmpeg.py        # FFmpeg 封装
│   ├── video.py         # 视频处理
│   ├── time.py          # 时间处理
│   └── text.py          # 文本处理
├── docker/              # Docker 配置
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── docker-compose.yml
├── requirements/        # 依赖管理
├── tests/               # 测试
├── docs/                # 文档
└── pyproject.toml       # 项目配置
```

### 运行测试

```bash
# 单元测试
pytest tests/ -v

# 测试覆盖率
pytest tests/ --cov=. --cov-report=html

# 类型检查
mypy .
```

### 代码规范

项目遵循以下规范：
- **PEP 8**: Python 代码风格
- **类型注解**: 使用 Python 3.10+ 类型提示
- **文档字符串**: Google 风格 docstring
- **Black**: 代码格式化
- **Ruff**: 代码检查

## Docker 部署

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 许可证

MIT License

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| 任务队列 | Celery + Redis |
| AI 服务 | 阿里云 DashScope (ASR, OCR, LLM, TTS) |
| 视频处理 | FFmpeg |
| 图像处理 | OpenCV |
| 存储后端 | Local, MinIO, S3 |
| 容器化 | Docker, Docker Compose |
