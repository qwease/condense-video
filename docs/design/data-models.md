# 数据模型 - Condense Video Python Backend

**设计日期**: 2026-02-27

## 1. 核心数据模型

### 1.1 转录结果 (ASR Output)

**来源**: DashScope paraformer-v2 ASR

```python
class Utterance(BaseModel):
    """单个语音片段"""
    text: str
    begin_time: int           # 毫秒
    end_time: int             # 毫秒
    words: list["Word"] = []

class Word(BaseModel):
    """字级别时间戳"""
    text: str
    begin_time: int           # 毫秒
    end_time: int             # 毫秒

class TranscriptResult(BaseModel):
    """ASR 转录结果"""
    utterances: list[Utterance]
```

**文件**: `steps/1_转录/transcript.json`

```json
{
  "utterances": [
    {
      "text": "传递函数的定义是...",
      "begin_time": 320,
      "end_time": 5660,
      "words": [
        { "text": "传", "begin_time": 320, "end_time": 400 },
        { "text": "递", "begin_time": 400, "end_time": 480 }
      ]
    }
  ]
}
```

### 1.2 转换后转录 (Sentences)

**来源**: 后处理智能分句

```python
class SubtitleWord(BaseModel):
    """字级别字幕"""
    text: str
    start: float              # 秒
    end: float                # 秒
    gap: float = 0.0          # 与下一个字的间隔 (秒)

class Sentence(BaseModel):
    """句子"""
    idx: int                  # 序号
    text: str
    start_idx: int            # 在 utterances 中的起始索引
    end_idx: int              # 在 utterances 中的结束索引
    start_time: float         # 开始时间 (秒)
    end_time: float           # 结束时间 (秒)
    duration: float           # 时长 (秒)
    words: list[SubtitleWord]

class TranscriptConverted(BaseModel):
    """转换后的转录"""
    subtitles_words: list[SubtitleWord]
    sentences: list[Sentence]
```

**文件**: `steps/2_文稿/transcript_converted.json`

```json
{
  "subtitles_words": [
    {
      "text": "传",
      "start": 0.32,
      "end": 0.40,
      "gap": 0.0
    }
  ],
  "sentences": [
    {
      "idx": 0,
      "text": "传递函数的定义是零初始条件下输出与输入之比",
      "start_idx": 0,
      "end_idx": 15,
      "start_time": 0.32,
      "end_time": 5.66,
      "duration": 5.34
    }
  ]
}
```

### 1.3 PPT 幻灯片 (OCR Output)

**来源**: DashScope VL OCR

```python
class SlideStructure(BaseModel):
    """PPT 结构化内容"""
    title: str = ""
    subtitles: list[str] = []
    body: list[str] = []
    formulas: list[str] = []
    key_terms: list[str] = []
    confidence: float = 0.0

class Slide(BaseModel):
    """单个幻灯片"""
    frame_id: int
    frame_path: str           # 图片路径或 URL
    timestamp: float          # 在视频中的时间戳 (秒)
    ocr_text: str             # OCR 原始文本
    structure: SlideStructure

class PPTResult(BaseModel):
    """PPT OCR 结果"""
    video_info: dict
    slides: list[Slide]
    chapters: list["Chapter"] = []
```

**文件**: `steps/5_PPT/ocr_result.json`

```json
{
  "video_info": {
    "path": "lecture.mp4",
    "duration": 5569.99,
    "fps": 30
  },
  "slides": [
    {
      "frame_id": 1,
      "frame_path": "frames/frame_0001.jpg",
      "timestamp": 0.0,
      "ocr_text": "第三章 控制系统的时域分析\n3.1 时域分析基础",
      "structure": {
        "title": "控制系统的时域分析",
        "subtitles": ["3.1 时域分析基础"],
        "body": [],
        "formulas": [],
        "key_terms": ["时域分析", "控制系统"],
        "confidence": 0.92
      }
    }
  ]
}
```

### 1.4 分类结果 (Classification)

**来源**: LLM 内容分类

```python
class ClassificationLabel(str, Enum):
    CORE = "core"              # 必留
    EXPLAIN = "explain"        # 可选
    INTERACT = "interact"      # 建议删
    CHAT = "chat"              # 必删
    TRANSITION = "transition"  # 可删

class Segment(BaseModel):
    """单个片段"""
    idx: int
    text: str
    start_idx: int
    end_idx: int
    start_time: float
    end_time: float
    label: ClassificationLabel
    confidence: float
    reason: str = ""           # 分类理由

class ClassificationResult(BaseModel):
    """分类结果"""
    segments: list[Segment]
    statistics: dict           # 各类型统计
```

**文件**: `steps/2_文稿/classification.json`

```json
{
  "segments": [
    {
      "idx": 0,
      "text": "传递函数的定义是...",
      "start_idx": 0,
      "end_idx": 15,
      "start_time": 0.32,
      "end_time": 5.66,
      "label": "core",
      "confidence": 0.95,
      "reason": "包含定义性陈述"
    }
  ],
  "statistics": {
    "total": 650,
    "core": 150,
    "explain": 200,
    "interact": 180,
    "chat": 80,
    "transition": 40
  }
}
```

### 1.5 章节大纲 (Outline)

**来源**: 基于 PPT 切换 + 语音聚类

```python
class Chapter(BaseModel):
    """章节"""
    id: int
    title: str
    start_slide: int          # 起始幻灯片 ID
    end_slide: int            # 结束幻灯片 ID
    start_idx: int            # 起始句子索引
    end_idx: int              # 结束句子索引
    start_time: float         # 开始时间 (秒)
    end_time: float           # 结束时间 (秒)
    duration: float           # 时长 (秒)
    core_sentences: int       # 核心句子数量
    keywords: list[str]       # 关键词
    key_formulas: list[str]   # 关键公式

class OutlineResult(BaseModel):
    """课程大纲"""
    title: str
    total_duration: float
    total_sentences: int
    chapters: list[Chapter]
```

**文件**: `steps/2_文稿/outline.json`

```json
{
  "title": "自动控制原理",
  "total_duration": 5569.99,
  "total_sentences": 650,
  "chapters": [
    {
      "id": 1,
      "title": "典型环节与传递函数",
      "start_slide": 1,
      "end_slide": 5,
      "start_idx": 0,
      "end_idx": 278,
      "start_time": 0.32,
      "end_time": 56.66,
      "duration": 56.34,
      "core_sentences": 25,
      "keywords": ["传递函数", "标准式", "增益"],
      "key_formulas": ["G(s) = 1/(Ts+1)"]
    }
  ]
}
```

### 1.6 TTS 音频

**来源**: DashScope CosyVoice / Edge TTS

```python
class TTSSegment(BaseModel):
    """单个 TTS 片段"""
    text: str
    audio_file: str           # 音频文件路径或 URL
    duration: float           # 时长 (秒)
    start_time: float = 0.0   # 在合成音频中的开始时间

class TTSTiming(BaseModel):
    """TTS 时间信息"""
    segments: list[TTSSegment]
    total_duration: float
```

**文件**: `steps/3_音频/audio_timing.json`

```json
{
  "segments": [
    {
      "text": "传递函数的定义是零初始条件下输出与输入之比",
      "audio_file": "segment_000.mp3",
      "duration": 3.2,
      "start_time": 0.0
    }
  ],
  "total_duration": 2150.0
}
```

### 1.7 最终输出 (Video Output)

**来源**: FFmpeg 剪辑合成

```python
class VideoOutput(BaseModel):
    """视频输出"""
    condensed_video_url: str           # 浓缩视频
    condensed_video_tts_url: str       # 带 TTS 的浓缩视频
    outline_url: str                   # 课程大纲
    summary_url: str                   # 课程总结
    key_points_url: str                # 核心要点

    # 统计信息
    duration_original: float
    duration_condensed: float
    compression_ratio: float

    # 文件清单
    files: dict[str, str]              # 各步骤输出文件
```

## 2. Redis 数据结构

### 2.1 任务状态

```
Key: task:{task_id}
Type: Hash
Fields:
  - status: pending | processing | success | failed | cancelled
  - progress: 0.0 - 1.0
  - current_step: asr_transcribe
  - message: 正在处理...
  - result_json: (JSON string, 完成时)
  - error: (错误信息)
  - created_at: ISO datetime
  - updated_at: ISO datetime
TTL: 7天
```

### 2.2 任务进度

```
Key: task-progress:{task_id}:latest
Type: String (JSON)
Value: {
  "step": "asr_transcribe",
  "progress": 0.5,
  "message": "正在转录...",
  "data": {},
  "timestamp": "2026-02-27T10:00:00Z"
}
TTL: 7天
```

### 2.3 进度频道

```
Channel: progress:{task_id}
Type: Pub/Sub
Message: 同 task-progress:{task_id}:latest 的 JSON
```

### 2.4 任务结果

```
Key: task-result:{task_id}
Type: String (JSON)
Value: VideoOutput (JSON)
TTL: 30天
```

### 2.5 Redis 客户端实现

```python
# services/redis_client.py

import json
from datetime import datetime
from redis import Redis
from core.config import settings

# Redis 客户端实例
redis = Redis.from_url(settings.redis_url, decode_responses=True)


# ==================== 任务状态 ====================
def set_task_status(
    task_id: str,
    status: str,
    progress: float = 0.0,
    current_step: str = "",
    message: str = "",
    result: dict | None = None,
    error: str | None = None
):
    """设置任务状态"""
    key = f"task:{task_id}"
    now = datetime.now().isoformat()

    # 获取现有数据
    existing = redis.hgetall(key)
    created_at = existing.get("created_at", now)

    data = {
        "status": status,
        "progress": str(progress),
        "current_step": current_step,
        "message": message,
        "created_at": created_at,
        "updated_at": now
    }

    if result:
        data["result_json"] = json.dumps(result)
    if error:
        data["error"] = error

    redis.hset(key, mapping=data)
    redis.expire(key, settings.redis_progress_ttl)


def get_task_status(task_id: str) -> dict | None:
    """获取任务状态"""
    data = redis.hgetall(f"task:{task_id}")
    if not data:
        return None

    # 转换类型
    if "progress" in data:
        data["progress"] = float(data["progress"])
    if "result_json" in data:
        data["result"] = json.loads(data["result_json"])

    return data


# ==================== 进度更新 ====================
def update_progress(
    task_id: str,
    step: str,
    progress: float,
    message: str,
    data: dict | None = None
):
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
    redis.set(f"{key}:latest", json.dumps(payload), ex=settings.redis_progress_ttl)

    # 发布到频道 (WebSocket 订阅)
    redis.publish(f"progress:{task_id}", json.dumps(payload))

    # 同步更新任务状态
    set_task_status(task_id, "processing", progress, step, message)


def get_progress(task_id: str) -> dict | None:
    """获取最新进度"""
    data = redis.get(f"task-progress:{task_id}:latest")
    return json.loads(data) if data else None


# ==================== 结果存储 ====================
def save_result(task_id: str, result: dict):
    """保存任务结果"""
    key = f"task-result:{task_id}"
    redis.set(key, json.dumps(result), ex=settings.redis_result_ttl)


def get_result(task_id: str) -> dict | None:
    """获取任务结果"""
    data = redis.get(f"task-result:{task_id}")
    return json.loads(data) if data else None


# ==================== 任务管理 ====================
def delete_task(task_id: str):
    """删除任务相关数据"""
    keys = [
        f"task:{task_id}",
        f"task-progress:{task_id}:latest",
        f"task-result:{task_id}"
    ]
    redis.delete(*keys)


def list_active_tasks() -> list[str]:
    """列出所有活动任务"""
    pattern = "task:*"
    task_ids = []
    for key in redis.scan_iter(match=pattern):
        task_id = key.split(":")[1]
        status = redis.hget(key, "status")
        if status in ["pending", "processing"]:
            task_ids.append(task_id)
    return task_ids
```

## 3. 文件命名约定

### 3.1 输出目录结构

```
output/
└── YYYY-MM-DD_视频名/
    └── 精要提炼/
        └── steps/
            ├── 1_转录/
            │   ├── audio.mp3
            │   └── transcript.json
            ├── 2_文稿/
            │   ├── transcript_converted.json
            │   ├── subtitles_words.json
            │   ├── sentences.txt
            │   ├── classification.json
            │   ├── classification.md
            │   ├── outline.json
            │   ├── outline.md
            │   ├── condensed.txt
            │   ├── summary.md
            │   └── key_points.md
            ├── 3_音频/
            │   ├── segment_000.mp3
            │   ├── ...
            │   ├── audio_timing.json
            │   └── tts_audio.mp3
            ├── 4_视频/
            │   ├── temp/
            │   ├── condensed_course.mp4
            │   └── condensed_tts.mp4
            └── 5_PPT/
                ├── frames/
                │   └── images/
                │       ├── frame_00000.jpg
                │       └── ...
                └── ocr_result.json
```

### 3.2 存储路径映射

| 步骤 | 文件类型 | 存储路径 (对象存储) |
|------|----------|---------------------|
| 1_转录 | 音频 | `steps/1_转录/audio.mp3` |
| 1_转录 | 转录 | `steps/1_转录/transcript.json` |
| 2_文稿 | 分类 | `steps/2_文稿/classification.json` |
| 2_文稿 | 大纲 | `steps/2_文稿/outline.json` |
| 2_文稿 | 大纲 | `steps/2_文稿/outline.md` |
| 3_音频 | TTS | `steps/3_音频/tts_audio.mp3` |
| 4_视频 | 输出 | `steps/4_视频/condensed_tts.mp4` |
| 5_PPT | 帧 | `steps/5_PPT/frames/images/*.jpg` |
| 5_PPT | OCR | `steps/5_PPT/ocr_result.json` |

## 4. 原数据模型 vs 新数据模型

### 4.1 主要变化

| 方面 | 原 JS 模型 | 新 Python 模型 |
|------|------------|----------------|
| 配置 | config.json | .env 文件 |
| 任务状态 | 文件系统 | Redis |
| 进度跟踪 | 无 | Redis Pub/Sub |
| 文件路径 | 相对路径 | 可配置的 URL |
| 类型检查 | 无 | Pydantic 验证 |

### 4.2 兼容性

新设计完全兼容原 JS 输出文件格式：
- `transcript.json` - 相同
- `ocr_result.json` - 相同
- `classification.json` - 相同
- `outline.json` - 相同

原 JS 生成的内容可以被新 Python 服务读取和处理。
