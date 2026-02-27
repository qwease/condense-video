# API 接口设计 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. REST API 端点

### 1.1 视频处理

#### POST /api/v1/videos/process

提交视频处理任务

**请求方式**:
- `multipart/form-data`: 上传视频文件
- `application/json`: 提供视频链接

**请求参数**:
```json
{
  "video_url": "https://example.com/video.mp4",  // 可选，与 video_file 二选一
  "workflow": "essential",                        // 工作流: essential | complete
  "tts_engine": "dashscope",                      // TTS 引擎: dashscope | edgetts
  "voice": "Cherry",                             // 音色
  "skip_transcribe": false,                      // 跳过转录
  "skip_ocr": false,                             // 跳过 OCR
  "options": {                                   // 其他选项
    "cutting_mode": "essential"
  }
}
```

**响应**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "progress": 0.0,
  "current_step": null,
  "message": "任务已提交，等待处理",
  "created_at": "2026-02-27T10:00:00Z",
  "updated_at": "2026-02-27T10:00:00Z"
}
```

#### GET /api/v1/tasks/{task_id}

查询任务状态

**响应**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",           // pending | processing | success | failed | cancelled
  "progress": 0.45,                  // 0.0 - 1.0
  "current_step": "asr_transcribe",
  "message": "正在转录语音...",
  "created_at": "2026-02-27T10:00:00Z",
  "updated_at": "2026-02-27T10:05:00Z",
  "result": null                    // 完成后包含结果
}
```

#### GET /api/v1/videos/{video_id}

获取视频处理结果

**响应**:
```json
{
  "video_id": "video_123",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "result": {
    // ============== 最终输出 ==============
    "condensed_video_url": "https://storage.example.com/videos/condensed_123.mp4",
    "condensed_video_with_tts_url": "https://storage.example.com/videos/condensed_tts_123.mp4",

    // ============== 2_文稿 步骤输出 ==============
    "script": {
      // 转换后的转录 (句子级别)
      "transcript_converted": {
        "url": "https://storage.example.com/results/transcript_converted.json",
        "description": "转换后的转录，包含句子和静音标记"
      },
      // 分类结果
      "classification": {
        "json_url": "https://storage.example.com/results/classification.json",
        "md_url": "https://storage.example.com/results/classification.md",
        "description": "AI 内容分类结果 (每句话的标签)"
      },
      // 章节大纲
      "outline": {
        "json_url": "https://storage.example.com/results/outline.json",
        "md_url": "https://storage.example.com/results/outline.md",
        "description": "课程章节大纲和结构"
      },
      // 浓缩文本 (用于 TTS)
      "condensed_text": {
        "url": "https://storage.example.com/results/condensed.txt",
        "description": "浓缩后的精要文本"
      },
      // 总结
      "summary": {
        "url": "https://storage.example.com/results/summary.md",
        "description": "课程总结"
      },
      // 核心要点
      "key_points": {
        "url": "https://storage.example.com/results/key_points.md",
        "description": "核心要点列表"
      }
    },

    // ============== 其他步骤输出 ==============
    "steps": {
      // 1_转录
      "transcribe": {
        "audio_url": "https://storage.example.com/steps/1_转录/audio.mp3",
        "transcript_url": "https://storage.example.com/steps/1_转录/transcript.json"
      },
      // 3_音频
      "audio": {
        "tts_segments_dir": "https://storage.example.com/steps/3_音频/",
        "audio_timing_url": "https://storage.example.com/steps/3_音频/audio_timing.json",
        "tts_audio_url": "https://storage.example.com/steps/3_音频/tts_audio.mp3"
      },
      // 4_视频
      "video": {
        "output_dir": "https://storage.example.com/steps/4_视频/",
        "condensed_video_url": "https://storage.example.com/steps/4_视频/condensed_course.mp4"
      },
      // 5_PPT
      "ppt": {
        "frames_dir": "https://storage.example.com/steps/5_PPT/frames/images/",
        "ocr_result_url": "https://storage.example.com/steps/5_PPT/ocr_result.json"
      }
    },

    // ============== 统计信息 ==============
    "statistics": {
      "duration": {
        "original": 5569.99,
        "condensed": 2150.00,
        "ratio": 0.386
      },
      "sentences": {
        "total": 650,
        "core": 150,
        "explain": 200,
        "interact": 180,
        "chat": 80,
        "transition": 40
      },
      "chapters_count": 12
    },

    // ============== 章节信息 (来自 outline.json) ==============
    "chapters": [
      {
        "id": 1,
        "title": "典型环节与传递函数",
        "start_time": 0.0,
        "end_time": 120.5,
        "duration": 120.5,
        "core_sentences": 25,
        "keywords": ["传递函数", "标准式", "增益"],
        "key_formulas": ["G(s) = 1/(Ts+1)"]
      }
    ]
  }
}
```

#### GET /api/v1/videos/{video_id}/file/{file_type}

下载特定文件

**参数**:
- `file_type`: 文件类型
  - `condensed_video` - 浓缩视频
  - `condensed_video_tts` - 带 TTS 的浓缩视频
  - `transcript` - 转录结果
  - `classification_json` - 分类结果 (JSON)
  - `classification_md` - 分类报告 (MD)
  - `outline_json` - 章节大纲 (JSON)
  - `outline_md` - 章节大纲 (MD)
  - `summary` - 课程总结
  - `key_points` - 核心要点
  - `condensed_text` - 浓缩文本

**响应**: 文件流

#### GET /api/v1/videos/{video_id}/download

下载处理后的视频 (默认 condensed_video_tts)

**响应**: 视频文件流

#### DELETE /api/v1/tasks/{task_id}

取消任务

**响应**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "任务已取消"
}
```

#### GET /api/v1/tasks/{task_id}/logs

获取任务日志

**参数**:
- `limit`: 返回条数 (默认 100)

**响应**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "logs": [
    {
      "timestamp": "2026-02-27T10:00:00Z",
      "level": "INFO",
      "step": "audio_extract",
      "message": "音频提取完成"
    }
  ]
}
```

### 1.2 系统接口

#### GET /health

健康检查

**响应**:
```json
{
  "status": "healthy",  // healthy | unhealthy
  "checks": {
    "api": {"status": "healthy"},
    "redis": {"status": "healthy", "detail": "connected"},
    "celery": {"status": "healthy", "detail": "2 worker(s) active"},
    "storage": {"status": "healthy", "detail": "minio"}
  }
}
```

#### GET /config

获取当前配置 (调试用)

**响应**:
```json
{
  "ocr": {
    "concurrency": 5,
    "model": "qwen-vl-plus"
  },
  "classification": {
    "concurrency": 10,
    "batch_size": 50
  },
  "cutting_modes": {
    "essential": {
      "description": "精要版 - 仅保留核心知识",
      "delete_labels": ["interact", "chat", "transition"]
    },
    "complete": {
      "description": "完整版 - 保留核心+解释",
      "delete_labels": ["chat"]
    }
  }
}
```

#### GET /metrics

Prometheus 指标

**响应**: Prometheus 文本格式

## 2. WebSocket 接口

### 2.1 任务进度推送

#### WS /ws/tasks/{task_id}

实时接收任务进度

**连接**:
```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/tasks/${taskId}`);
```

**服务端推送消息**:
```json
{
  "type": "progress",
  "step": "asr_transcribe",
  "progress": 0.5,
  "message": "正在转录语音... 50%",
  "data": {
    "processed": 150,
    "total": 300
  },
  "timestamp": "2026-02-27T10:05:00Z"
}
```

**消息类型**:
| 类型 | 说明 |
|------|------|
| `progress` | 进度更新 |
| `step_complete` | 步骤完成 |
| `step_failed` | 步骤失败 |
| `task_complete` | 任务完成 |
| `task_failed` | 任务失败 |
| `task_cancelled` | 任务取消 |

## 3. 任务步骤枚举

```python
class TaskStep(Enum):
    VIDEO_DOWNLOAD = "video_download"        # 视频下载
    AUDIO_EXTRACT = "audio_extract"          # 音频提取
    PPT_EXTRACT = "ppt_extract"              # PPT 提取
    ASR_TRANSCRIBE = "asr_transcribe"        # 语音转录
    PPT_OCR = "ppt_ocr"                      # OCR 识别
    CONTENT_CLASSIFY = "content_classify"    # 内容分类
    CHAPTER_SEGMENT = "chapter_segment"      # 章节切分
    CONTENT_SUMMARIZE = "content_summarize"  # 内容总结
    TTS_GENERATE = "tts_generate"            # TTS 生成
    VIDEO_EDIT = "video_edit"                # 视频剪辑
    CLEANUP = "cleanup"                      # 清理
```

## 4. 步骤权重 (进度计算)

```python
STEP_WEIGHTS = {
    TaskStep.VIDEO_DOWNLOAD: 0.05,
    TaskStep.AUDIO_EXTRACT: 0.05,
    TaskStep.PPT_EXTRACT: 0.05,
    TaskStep.ASR_TRANSCRIBE: 0.15,      # 最耗时
    TaskStep.PPT_OCR: 0.15,             # 最耗时
    TaskStep.CONTENT_CLASSIFY: 0.10,
    TaskStep.CHAPTER_SEGMENT: 0.05,
    TaskStep.CONTENT_SUMMARIZE: 0.10,
    TaskStep.TTS_GENERATE: 0.15,
    TaskStep.VIDEO_EDIT: 0.10,
    TaskStep.CLEANUP: 0.05,
}
```

## 5. 2_文稿 步骤输出文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `transcript_converted.json` | JSON | 转换后的转录，包含句子级别和静音标记 |
| `subtitles_words.json` | JSON | 字幕 + 静音标记 |
| `sentences.txt` | TXT | 句子列表 (idx\|startIdx-endIdx\|text) |
| `classification.json` | JSON | 每句话的分类标签 (core/explain/interact/chat/transition) |
| `classification.md` | MD | 分类报告和统计 |
| `outline.json` | JSON | 结构化章节大纲 |
| `outline.md` | MD | 课程大纲 (可读格式) |
| `condensed.txt` | TXT | 浓缩后的精要文本 (用于 TTS) |
| `summary.md` | MD | 完整课程总结 |
| `key_points.md` | MD | 核心要点列表 |

## 6. 错误响应格式

```json
{
  "error": {
    "code": "ASR_TRANSCRIBE_FAILED",
    "message": "语音转录失败，请检查音频文件",
    "details": {
      "original_error": "DashScope API error: invalid file format"
    }
  }
}
```

**错误代码**:
| 代码 | 说明 |
|------|------|
| `TASK_NOT_FOUND` | 任务不存在 |
| `INVALID_VIDEO` | 无效的视频文件 |
| `ASR_TRANSCRIBE_FAILED` | ASR 转录失败 |
| `OCR_RECOGNITION_FAILED` | OCR 识别失败 |
| `LLM_CLASSIFICATION_FAILED` | LLM 分类失败 |
| `TTS_GENERATION_FAILED` | TTS 生成失败 |
| `VIDEO_EDIT_FAILED` | 视频剪辑失败 |
| `STORAGE_ERROR` | 存储错误 |
