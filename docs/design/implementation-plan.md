# 实现计划 - Condense Video Python Backend

**设计日期**: 2026-02-27
**预计工期**: 5-7 天

## 1. 实现阶段划分

### 第一阶段：项目基础搭建 (Day 1)
### 第二阶段：核心服务实现 (Day 2-3)
### 第三阶段：Celery 工作流实现 (Day 3-4)
### 第四阶段：API 层实现 (Day 4-5)
### 第五阶段：测试与部署 (Day 5-6)

---

## 2. 详细任务清单

### 第一阶段：项目基础搭建 (Day 1)

#### 2.1.1 项目初始化
- [ ] 创建项目目录结构
- [ ] 初始化 Python 项目 (`pyproject.toml`)
- [ ] 配置 Git (`.gitignore`)
- [ ] 创建 `.env.example`

#### 2.1.2 配置管理
- [ ] 实现 `core/config.py`
  - [ ] `AppConfig` 类
  - [ ] 环境变量加载
  - [ ] 配置验证
- [ ] 编写配置测试

#### 2.1.3 依赖安装
- [ ] 创建 `requirements/base.txt`
- [ ] 创建 `requirements/api.txt`
- [ ] 创建 `requirements/worker.txt`
- [ ] 本地验证依赖安装

#### 2.1.4 基础组件
- [ ] 实现 `core/exceptions.py`
- [ ] 实现 `core/logging.py`
- [ ] 实现 `core/metrics.py`

---

### 第二阶段：核心服务实现 (Day 2-3)

#### 2.2.1 DashScope 服务客户端
- [ ] 实现 `services/dashscope.py`
  - [ ] ASR 转录方法
  - [ ] OCR 识别方法
  - [ ] LLM 分类方法
  - [ ] TTS 生成方法
  - [ ] 错误处理和重试

#### 2.2.2 Redis 客户端
- [ ] 实现 `services/redis_client.py`
  - [ ] 任务状态存储
  - [ ] 进度更新和发布
  - [ ] 结果存储

#### 2.2.3 存储抽象层
- [ ] 实现 `core/storage.py`
  - [ ] `StorageBackend` 抽象类
  - [ ] `LocalStorage` 实现
  - [ ] `MinIOStorage` 实现
  - [ ] 存储工厂函数

#### 2.2.4 FFmpeg 工具
- [ ] 实现 `utils/ffmpeg.py`
  - [ ] `extract_audio()` 提取音频
  - [ ] `extract_frames()` 提取关键帧
  - [ ] `concat_videos()` 合成视频
  - [ ] `merge_audio_video()` 音视频合成

#### 2.2.5 进度推送
- [ ] 实现 `core/progress.py`
  - [ ] `update_progress()` 函数
  - [ ] Redis Pub/Sub 集成

#### 2.2.6 规则迁移
- [ ] 迁移 `规则/1-内容分类.md` → `core/rules/classification.py`
- [ ] 迁移 `规则/2-结构提取.md` → `core/rules/structure.py`
- [ ] 迁移 `规则/3-总结生成.md` → `core/rules/summary.py`
- [ ] 迁移 `规则/4-PPT分析.md` → `core/rules/ppt.py`

---

### 第三阶段：Celery 工作流实现 (Day 3-4)

#### 2.3.1 Celery 配置
- [ ] 实现 `tasks/celery_app.py`
  - [ ] Celery 实例配置
  - [ ] 任务路由配置
  - [ ] 队列定义

#### 2.3.2 视频处理任务
- [ ] `tasks/video/download.py` - 视频下载/接收
- [ ] `tasks/video/audio_extract.py` - 音频提取
- [ ] `tasks/video/edit.py` - 视频剪辑合成

#### 2.3.3 ASR 任务
- [ ] `tasks/asr/transcribe.py` - 语音转录
  - [ ] 上传音频到公网 URL (可选)
  - [ ] 调用 DashScope ASR
  - [ ] 结果处理和存储

#### 2.3.4 PPT 任务
- [ ] `tasks/ppt/extract.py` - PPT 关键帧提取
- [ ] `tasks/ppt/ocr.py` - OCR 识别
  - [ ] 并发处理
  - [ ] 批处理优化

#### 2.3.5 LLM 任务
- [ ] `tasks/llm/classify.py` - 内容分类
  - [ ] 融合语音 + PPT
  - [ ] 批处理
- [ ] `tasks/llm/segment.py` - 章节切分
- [ ] `tasks/llm/summarize.py` - 内容总结

#### 2.3.6 TTS 任务
- [ ] `tasks/tts/generate.py` - TTS 生成
  - [ ] DashScope TTS
  - [ ] Edge TTS
  - [ ] 并发处理

#### 2.3.7 工作流编排
- [ ] 实现 `tasks/workflows.py`
  - [ ] 并行工作流 (ASR + OCR)
  - [ ] 串行工作流 (分类 → 章节 → 总结 → TTS → 剪辑)
  - [ ] 错误处理
  - [ ] 断点续传

---

### 第四阶段：API 层实现 (Day 4-5)

#### 2.4.1 数据模型
- [ ] 实现 `api/models/task.py`
- [ ] 实现 `api/models/video.py`
- [ ] 实现 `api/schemas/` 请求/响应 Schema

#### 2.4.2 API 路由
- [ ] `api/routers/videos.py`
  - [ ] `POST /api/v1/videos/process`
  - [ ] `GET /api/v1/videos/{video_id}`
  - [ ] `GET /api/v1/videos/{video_id}/download`
  - [ ] `GET /api/v1/videos/{video_id}/file/{file_type}`

- [ ] `api/routers/tasks.py`
  - [ ] `GET /api/v1/tasks/{task_id}`
  - [ ] `DELETE /api/v1/tasks/{task_id}`
  - [ ] `GET /api/v1/tasks/{task_id}/logs`

- [ ] `api/routers/health.py`
  - [ ] `GET /health`
  - [ ] `GET /config`
  - [ ] `GET /metrics`

#### 2.4.3 WebSocket
- [ ] `api/routers/ws.py`
  - [ ] `WS /ws/tasks/{task_id}` 实时进度

#### 2.4.4 FastAPI 入口
- [ ] 实现 `api/main.py`
  - [ ] 应用初始化
  - [ ] 中间件配置
  - [ ] 路由注册
  - [ ] CORS 配置

---

### 第五阶段：测试与部署 (Day 5-6)

#### 2.5.1 单元测试
- [ ] 测试配置加载
- [ ] 测试 DashScope 客户端
- [ ] 测试 Redis 操作
- [ ] 测试存储操作
- [ ] 测试各个 Celery 任务

#### 2.5.2 集成测试
- [ ] 测试完整工作流
- [ ] 测试 API 端点
- [ ] 测试 WebSocket 连接

#### 2.5.3 Docker 部署
- [ ] 创建 `docker/Dockerfile.api`
- [ ] 创建 `docker/Dockerfile.worker`
- [ ] 创建 `docker/docker-compose.yml`
- [ ] 编写 `scripts/start.sh`

#### 2.5.4 文档
- [ ] 更新 `README.md`
- [ ] API 文档 (FastAPI 自动生成)
- [ ] 部署文档

---

## 3. 实施顺序建议

### 优先级 P0 (核心功能)
1. 配置管理
2. DashScope 服务客户端
3. Redis 客户端
4. Celery 配置
5. ASR 任务
6. OCR 任务
7. 内容分类任务
8. 工作流编排
9. API 基础路由

### 优先级 P1 (重要功能)
10. 章节切分任务
11. TTS 任务
12. 视频剪辑任务
13. WebSocket 进度推送
14. 存储抽象层

### 优先级 P2 (增强功能)
15. 断点续传
16. 任务取消
17. 日志查询
18. 监控指标
19. MinIO 存储

---

## 4. 验收标准

### 4.1 功能验收
- [ ] 能够上传/指定视频进行处理
- [ ] ASR 转录正常工作
- [ ] OCR 识别正常工作
- [ ] 内容分类准确
- [ ] 生成浓缩视频
- [ ] API 响应正常
- [ ] WebSocket 实时推送进度

### 4.2 性能验收
- [ ] 并行处理 ASR 和 OCR，时间减少 >30%
- [ ] 支持至少 2 个 Worker 并发
- [ ] 任务状态查询延迟 <100ms

### 4.3 稳定性验收
- [ ] 任务失败自动重试
- [ ] Worker 崩溃后任务恢复
- [ ] 服务重启后任务状态保留

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| DashScope API 限流 | 处理变慢 | 实现请求队列，支持配置并发数 |
| 视频文件过大 | 存储压力 | 支持分块上传，流式处理 |
| Worker 内存溢出 | 任务失败 | 限制任务并发，实现内存监控 |
| FFmpeg 版本兼容 | 处理失败 | 固定 FFmpeg 版本 |

---

## 6. 技术债务追踪

在实现过程中发现的暂时妥协：
- [ ] 原有的 JS 脚本未完全迁移，保留兼容性
- [ ] 规则文件使用 Markdown，后续可考虑 DSL
- [ ] 暂未实现数据库，仅使用 Redis
