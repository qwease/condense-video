# Docker 部署 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. Docker Compose 配置

```yaml
# docker/docker-compose.yml

version: '3.8'

services:
  # ============== Redis ==============
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ============== MinIO (对象存储) ==============
  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    volumes:
      - minio_data:/data
    command: server /data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # ============== FastAPI 服务 ==============
  api:
    build:
      context: ..
      dockerfile: docker/Dockerfile.api
    ports:
      - "${API_PORT:-8000}:8000"
    env_file:
      - ../.env
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ../data:/app/data
      - ../rules:/app/rules:ro
    depends_on:
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000

  # ============== Celery Worker ==============
  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile.worker
    env_file:
      - ../.env
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ../data:/app/data
      - ../rules:/app/rules:ro
      - /tmp/ffmpeg:/tmp/ffmpeg
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      replicas: ${WORKER_REPLICAS:-2}
    command: celery -A tasks.celery_app worker --loglevel=info --concurrency=${WORKER_CONCURRENCY:-2}

  # ============== Flower (Celery 监控面板) ==============
  flower:
    build:
      context: ..
      dockerfile: docker/Dockerfile.worker
    ports:
      - "5555:5555"
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
    depends_on:
      - redis
    command: celery -A tasks.celery_app flower --port=5555 --broker=redis://redis:6379/0

volumes:
  redis_data:
  minio_data:

networks:
  default:
    name: condense-video-network
```

## 2. Dockerfile - API

```dockerfile
# docker/Dockerfile.api

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements/api.txt requirements.txt

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 3. Dockerfile - Worker

```dockerfile
# docker/Dockerfile.worker

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖 (包含 FFmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements/worker.txt requirements.txt

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 复制规则文件
COPY rules /app/rules

# 创建必要的目录
RUN mkdir -p /app/data/temp && \
    mkdir -p /tmp/ffmpeg

# 暴露 Flower 端口 (用于监控)
EXPOSE 5555

# 启动命令 (由 docker-compose 覆盖)
CMD ["celery", "-A", "tasks.celery_app", "worker", "--loglevel=info"]
```

## 4. 依赖文件

### 4.1 基础依赖 (base.txt)

```txt
# requirements/base.txt

pydantic>=2.0
pydantic-settings>=2.0
pydantic[email]

redis>=5.0
httpx>=0.24

python-dotenv>=1.0

python-multipart>=0.0.6

# 日志
loguru>=0.7

# 工具
tenacity>=8.2
```

### 4.2 API 依赖 (api.txt)

```txt
# requirements/api.txt

-r base.txt

# Web 框架
fastapi>=0.104
uvicorn[standard]>=0.24
websockets>=12.0

# Celery (客户端)
celery[redis]>=5.3
flower>=2.0

# 监控
prometheus-client>=0.19
```

### 4.3 Worker 依赖 (worker.txt)

```txt
# requirements/worker.txt

-r base.txt

# Celery (Worker)
celery[redis]>=5.3

# 视频处理
opencv-python>=4.8
Pillow>=10.0
imagehash>=4.3

# HTTP 客户端
httpx[http2]>=0.24

# Edge TTS
edge-tts>=6.1

# MinIO (可选)
minio>=7.0
```

## 5. 启动脚本

```bash
#!/bin/bash
# scripts/start.sh

set -e

echo "🚀 Starting Condense Video Backend..."

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  .env file not found, copying from .env.example..."
    cp .env.example .env
    echo "❗ Please edit .env file with your API keys and configuration"
    exit 1
fi

# 创建必要的目录
mkdir -p data/temp data/videos data/output

# 构建镜像
echo "📦 Building Docker images..."
docker-compose -f docker/docker-compose.yml build

# 启动服务
echo "🎬 Starting services..."
docker-compose -f docker/docker-compose.yml up -d

echo ""
echo "✅ Services started!"
echo ""
echo "📊 Dashboard:"
echo "   - API:      http://localhost:8000"
echo "   - Docs:     http://localhost:8000/docs"
echo "   - Flower:   http://localhost:5555"
echo "   - MinIO:    http://localhost:9001"
echo ""
echo "📝 Logs:"
echo "   docker-compose -f docker/docker-compose.yml logs -f"
```

## 6. 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI | 8000 | API 服务 |
| WebSocket | 8000 | WS 连接 (与 API 共用) |
| Redis | 6379 | 消息队列/缓存 |
| MinIO API | 9000 | 对象存储 API |
| MinIO Console | 9001 | MinIO 管理界面 |
| Flower | 5555 | Celery 监控面板 |

## 7. 健康检查

```bash
# 检查所有服务状态
docker-compose -f docker/docker-compose.yml ps

# 检查 API 健康
curl http://localhost:8000/health

# 检查 Redis
docker-compose -f docker/docker-compose.yml exec redis redis-cli ping

# 查看 Worker 日志
docker-compose -f docker/docker-compose.yml logs -f worker
```

## 8. 扩展 Worker

```bash
# 增加 Worker 副本
export WORKER_REPLICAS=4
docker-compose -f docker/docker-compose.yml up -d --scale worker=4

# 增加单个 Worker 并发
export WORKER_CONCURRENCY=4
docker-compose -f docker/docker-compose.yml up -d worker
```

## 9. 常用命令

```bash
# 启动所有服务
docker-compose -f docker/docker-compose.yml up -d

# 停止所有服务
docker-compose -f docker/docker-compose.yml down

# 查看日志
docker-compose -f docker/docker-compose.yml logs -f [service]

# 重启服务
docker-compose -f docker/docker-compose.yml restart [service]

# 重新构建镜像
docker-compose -f docker/docker-compose.yml build

# 清理所有数据
docker-compose -f docker/docker-compose.yml down -v
```

## 10. 生产环境部署建议

### 10.1 使用外部服务

生产环境建议使用托管服务：

| 组件 | 开发环境 | 生产环境 |
|------|----------|----------|
| Redis | Docker Redis | Redis Cloud / AWS ElastiCache |
| 存储 | MinIO | AWS S3 / 阿里云 OSS |
| 监控 | Flower | Flower + Sentry |

### 10.2 环境变量

```bash
# .env.production

# API
API_WORKERS=4
API_RELOAD=false

# Celery
WORKER_CONCURRENCY=4
WORKER_REPLICAS=3

# 存储 (使用 AWS S3)
STORAGE_BACKEND=s3
S3_BUCKET=condense-video-prod
S3_REGION=us-east-1

# DashScope (生产密钥)
DASHSCOPE_API_KEY=sk-prod-xxx
```

### 10.3 安全配置

1. **限制 CORS 来源**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],
    allow_credentials=True,
)
```

2. **添加 API 认证**
```python
from fastapi import Security
from api.dependencies import verify_api_key

@router.post("/api/v1/videos/process", dependencies=[Security(verify_api_key)])
async def process_video(...):
    ...
```

3. **启用 HTTPS** (使用 Nginx 反向代理)
```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
