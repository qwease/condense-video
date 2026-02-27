# 进度记录: Phase 4 - Celery 任务实现

**日期**: 2026-02-27
**状态**: 已完成
**完成度**: 100%

---

## 已完成

### 4.1 视频处理任务 (tasks/video/)
- [x] `download.py` - 视频下载/接收
  - [x] `download_video` - 从 URL 下载视频
  - [x] `receive_video` - 接收本地视频
  - [x] `upload_video_to_storage` - 上传到对象存储
- [x] `audio_extract.py` - 音频提取
  - [x] `extract_audio_task` - 提取音频 (使用 FFmpeg)
  - [x] `upload_audio_for_asr` - 上传音频供 ASR 使用

### 4.2 ASR 转录任务 (tasks/asr/)
- [x] `transcribe.py` - 语音转录
  - [x] `transcribe_audio` - DashScope ASR 转录 (异步模式 + 轮询)
  - [x] `convert_transcript` - 转换转录结果格式 + 智能分句
  - [x] 支持 sentences.txt 和 subtitles_words.json 输出

### 4.3 PPT 处理任务 (tasks/ppt/)
- [x] `extract.py` - PPT 关键帧提取
  - [x] `extract_ppt_frames` - 关键帧提取
  - [x] 支持 FFmpeg 场景检测方法
  - [x] 支持 OpenCV 感知哈希方法 (更精确)
  - [x] 生成 frames_info.json
- [x] `ocr.py` - PPT OCR 识别
  - [x] `ocr_slides` - DashScope VL OCR 批量识别
  - [x] 结构化信息提取 (标题、正文、公式、关键词)
  - [x] 并发处理优化

### 4.4 LLM 处理任务 (tasks/llm/)
- [x] `classify.py` - 内容分类
  - [x] `classify_content` - 融合语音 + PPT 分类
  - [x] 支持 5 种分类标签 (core, explain, interact, chat, transition)
  - [x] 批量分类优化
  - [x] 生成 classification.md 报告
- [x] `segment.py` - 章节切分
  - [x] `segment_chapters` - 基于 PPT 切换切分章节
  - [x] 提取章节关键词和公式
  - [x] 生成 outline.json 和 outline.md
- [x] `summarize.py` - 内容总结
  - [x] `summarize_content` - 生成课程总结和核心要点
  - [x] `condense_for_tts` - 生成适合 TTS 的浓缩文本
  - [x] LLM 辅助总结生成

### 4.5 TTS 任务 (tasks/tts/)
- [x] `generate.py` - TTS 语音合成
  - [x] `generate_tts` - 生成 TTS 配音
  - [x] 支持 DashScope CosyVoice 引擎
  - [x] 支持 Edge TTS 引擎
  - [x] 批量生成 + 音频合并
  - [x] 生成 audio_timing.json

### 4.6 工作流编排 (tasks/)
- [x] `workflows.py` - 完整工作流
  - [x] `process_video_workflow` - 完整处理流程
  - [x] ASR 和 PPT 并行执行优化
  - [x] 断点续传框架
  - [x] 任务取消支持

---

## 进行中

**无** - Phase 4 已完成

---

## 待完成

### Phase 5-18: 其他功能模块
- [ ] API 层实现 (FastAPI 路由)
- [ ] WebSocket 进度推送
- [ ] 数据模型和 Schema
- [ ] 测试

---

## 问题与解决方案

### 问题 003: ASR 需要公网 URL

**日期**: 2026-02-27
**来源**: DashScope API 限制

**问题**: DashScope ASR API 需要公网可访问的音频 URL。

**解决方案**:
- 实现音频上传到对象存储 (MinIO/S3/本地)
- 返回公网可访问的 URL
- 临时文件自动清理

**实施状态**: ✅ 已完成

---

### 问题 004: PPT 关键帧提取方法选择

**日期**: 2026-02-27
**来源**: 技术选型

**问题**: 需要在速度和精度之间权衡。

**解决方案**:
- FFmpeg 场景检测: 快速但可能不够精确
- OpenCV 感知哈希: 精确但较慢
- 支持配置选择，默认使用 FFmpeg

**实施状态**: ✅ 已完成

---

## 文件清单

### 新创建的文件

| 文件路径 | 说明 |
|----------|------|
| `tasks/video/download.py` | 视频下载/接收任务 |
| `tasks/video/audio_extract.py` | 音频提取任务 |
| `tasks/asr/transcribe.py` | ASR 转录任务 |
| `tasks/ppt/extract.py` | PPT 关键帧提取任务 |
| `tasks/ppt/ocr.py` | PPT OCR 识别任务 |
| `tasks/llm/classify.py` | 内容分类任务 |
| `tasks/llm/segment.py` | 章节切分任务 |
| `tasks/llm/summarize.py` | 内容总结任务 |
| `tasks/tts/generate.py` | TTS 生成任务 |
| `tasks/workflows.py` | 工作流编排 |
| `docs/progress/phase-04-celery-tasks.md` | Phase 4 进度文档 |

---

## 设计决策

### 决策 005: 并行优化 - ASR 与 PPT 同时进行

**日期**: 2026-02-27
**来源**: 性能优化需求

**内容**: ASR 转录和 PPT OCR 是独立的，可以并行执行。

**原因**:
- 原设计为串行处理，总耗时 = ASR + PPT
- 并行处理后，总耗时 = max(ASR, PPT)
- 预计节省 30-40% 处理时间

**实施方案**:
- 使用 Celery `group` 实现并行
- 两个分支完成后进入下一阶段
- 结果自动合并传递

```python
parallel_step = group(asr_branch, ppt_branch)
chain(
    parallel_step,
    classify_step,  # 需要 ASR 和 PPT 都完成
    ...
)
```

---

### 决策 006: 智能分句策略

**日期**: 2026-02-27
**来源**: 参考 JS 实现

**内容**: 结合标点符号和静音间隔进行分句。

**原因**:
- 纯标点分句可能导致句子过长
- 纯静音分句可能在非句子边界分割
- 两者结合更合理

**实施方案**:
- 遇到 `。！？.!?` 标点时分句
- 静音间隔 >= 0.5 秒时也分句
- 优先按标点，标点间距过长时按静音

---

## 下一步计划

1. 实现 Phase 5: API 层
   - FastAPI 路由
   - 数据模型 (Pydantic)
   - WebSocket 进度推送

**预计完成时间**: 2026-02-27

---

## 验证标准

- [x] 所有任务文件已创建
- [x] 代码符合 Python 最佳实践
- [x] 类型注解完整
- [x] 文档字符串完整
- [x] 所有任务使用 Celery `@shared_task` 装饰
- [x] 支持任务重试和错误处理
- [x] 支持进度更新
- [x] 并行优化已实现
