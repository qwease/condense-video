# Docker Compose 部署指南

## 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| api | 8000 | FastAPI 服务 |
| worker | - | Celery 任务处理器 |
| redis | 6379 | Redis 消息队列 |
| minio | 9000, 9001 | 对象存储 (API: 9000, Console: 9001) |
| flower | 5555 | Celery 监控面板 |

## 快速启动

```bash
# 进入 docker 目录
cd docker

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f api
docker-compose logs -f worker

# 停止服务
docker-compose down
```

## 环境变量

复制 `.env.example` 到 `.env` 并配置：

```bash
cp .env.example .env
```

必需的环境变量：
- `DASHSCOPE_API_KEY`: DashScope API 密钥

## 验证服务

```bash
# 检查 API 健康
curl http://localhost:8000/api/v1/health

# 检查 Flower 监控
curl http://localhost:5555

# 提交测试任务
curl -X POST "http://localhost:8000/api/v1/videos/process" \
  -F "task_name=docker-test" \
  -F "video_url=file:///app/data/input/test.mp4" \
  -F "mode=essential"
```

## 扩展 Worker

```bash
# 增加 Worker 副本数
WORKER_REPLICAS=4 docker-compose up -d --scale worker=4

# 调整并发数
WORKER_CONCURRENCY=4 docker-compose up -d
```

## 数据持久化

- `data/`: 输入/输出文件
- `logs/`: 日志文件
- Docker volumes: `redis_data`, `minio_data`

## 故障排查

```bash
# 查看服务状态
docker-compose ps

# 重启服务
docker-compose restart api
docker-compose restart worker

# 查看容器日志
docker-compose logs --tail=100 worker

# 进入容器调试
docker-compose exec worker bash
docker-compose exec api bash
```
