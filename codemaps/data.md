# Data Models - condense-video

**Last Updated**: 2026-03-02

## Redis State Structures

Task state is stored in Redis with the following keys:

```python
# Task status
key: "task:{task_id}"
value: {
    "task_id": str,
    "status": "pending" | "processing" | "success" | "failed" | "cancelled",
    "progress": float,  # 0.0 - 1.0
    "current_step": str,
    "message": str,
    "created_at": ISO datetime,
    "updated_at": ISO datetime,
    "result": dict | None,
}
ttl: 2592000  # 30 days

# Task progress
key: "task:{task_id}:progress"
value: {
    "step": str,
    "progress": float,
    "message": str,
    "timestamp": ISO datetime,
}
ttl: 604800  # 7 days

# Task result
key: "task:{task_id}:result"
value: dict  # Final processing result
ttl: 2592000  # 30 days
```

## API Request/Response Schemas

### ProcessVideoRequest

```python
class ProcessVideoRequest(BaseModel):
    video_url: str | None = None      # Video URL
    video_name: str = "video"         # Output directory name
    mode: ProcessingMode = "essential"  # essential | complete
    tts_engine: TTSEngine = "dashscope"  # dashscope | edgetts
    voice: str = "Cherry"             # TTS voice name
    skip_transcribe: bool = False     # Skip ASR step
    skip_ocr: bool = False            # Skip OCR step
    options: dict | None = None       # Additional options
```

### TaskResponse

```python
class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus                 # pending | processing | success | failed | cancelled
    progress: float                    # 0.0 - 1.0
    current_step: str | None
    message: str
    created_at: datetime
    updated_at: datetime
    result: dict | None
```

### VideoProcessResult

```python
class VideoProcessResult(BaseModel):
    # Video outputs
    condensed_video_url: str | None
    condensed_video_tts_url: str | None

    # Script outputs
    script: ScriptFileInfo | None

    # Steps
    steps: StepFileInfo | None

    # Statistics
    statistics: Statistics | None

    # Chapters
    chapters: list[ChapterInfo]
```

## Core Data Schemas (Legacy)

## Core Data Schemas

### Transcript (ASR Output)

**File**: `steps/1_转录/transcript.json`

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

**Note**: DashScope paraformer-v2 returns a single long utterance with word-level timestamps.

### Converted Transcript (Sentences)

**File**: `steps/2_文稿/transcript_converted.json`

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
      "startIdx": 1,
      "endIdx": 50,
      "startTime": 0.32,
      "endTime": 5.66
    }
  ]
}
```

### PPT Slides (OCR Output)

**File**: `steps/5_PPT/ocr_result.json`

```json
{
  "videoInfo": {
    "path": "lecture.mp4",
    "duration": 5569.99,
    "fps": 30
  },
  "slides": [
    {
      "frameId": 1,
      "framePath": "frames/frame_0001.jpg",
      "timestamp": 0.0,
      "ocrText": "第三章 控制系统的时域分析\n3.1 时域分析基础",
      "structure": {
        "title": "控制系统的时域分析",
        "subtitles": ["3.1 时域分析基础"],
        "body": [],
        "formulas": [],
        "keyTerms": ["时域分析", "控制系统"],
        "confidence": 0.92
      }
    }
  ],
  "chapters": [
    {
      "id": 1,
      "title": "控制系统的时域分析",
      "startSlide": 1,
      "endSlide": 5,
      "startTime": 0.0,
      "endTime": 180.5
    }
  ]
}
```

### Classification Result

**File**: `steps/2_文稿/classification.json`

```json
{
  "segments": [
    {
      "idx": 0,
      "text": "传递函数的定义是...",
      "startIdx": 1,
      "endIdx": 50,
      "label": "core",
      "confidence": 0.95,
      "reason": "包含定义性陈述"
    }
  ]
}
```

### Chapters Outline

**File**: `steps/2_文稿/outline.json`

```json
{
  "title": "自动控制原理",
  "totalDuration": 5569.99,
  "chapters": [
    {
      "id": 1,
      "title": "典型环节与传递函数",
      "startIdx": 0,
      "endIdx": 278,
      "startTime": 0.32,
      "endTime": 56.66,
      "duration": 56.34,
      "coreSentences": 12,
      "keywords": ["传递函数", "标准式", "增益"]
    }
  ]
}
```

### TTS Audio Timing

**File**: `steps/3_音频/audio_timing.json`

```json
{
  "segments": [
    {
      "text": "传递函数的定义是...",
      "audioFile": "segment_000.mp3",
      "duration": 3.2,
      "startTime": 0.0
    }
  ]
}
```

## Classification Labels

| Label | Action | Description |
|-------|--------|-------------|
| `core` | Keep | Definitions, formulas, theorems, key concepts |
| `explain` | Optional | Explanations, examples |
| `interact` | Delete | Classroom interaction, Q&A |
| `chat` | Delete | Off-topic content |
| `transition` | Delete | Transition phrases |

## File Naming Conventions

```
output/
└── YYYY-MM-DD_视频名/
    └── 精要提炼/
        └── steps/
            ├── 1_转录/
            │   ├── audio.mp3              # Extracted audio
            │   └── transcript.json        # ASR result
            ├── 2_文稿/
            │   ├── transcript_converted.json  # Sentences with gaps
            │   ├── classification.json       # AI classification
            │   ├── classification.md        # Classification report
            │   ├── outline.md              # Course outline
            │   └── outline.json            # Structured chapters
            ├── 3_音频/
            │   ├── segment_000.mp3         # TTS segments
            │   └── audio_timing.json       # Timing info
            ├── 4_视频/
            │   ├── temp/                   # Temporary video segments
            │   └── condensed_course.mp4    # Final output
            └── 5_PPT/
                ├── frames/
                │   └── images/             # Key frame images
                └── ocr_result.json        # PPT OCR results
```

## Rule Files Structure

规则/ directory contains markdown files defining classification and extraction logic:

```
规则/
├── 1-内容分类.md      # Classification rules (core/explain/interact/chat/transition)
├── 2-结构提取.md      # Chapter detection rules
├── 3-总结生成.md      # Summary generation templates
└── 4-PPT分析.md       # PPT OCR and structure rules
```

Each rule file defines:
- Input data sources
- Output format
- Classification/extraction criteria
- Example patterns
