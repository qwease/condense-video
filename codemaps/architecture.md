# Architecture - condense-video

**Last Updated**: 2026-02-27

## Overview

Course video content extraction skill (课程视频内容提炼). Combines speech transcription and PPT OCR analysis to extract core knowledge from long videos, filtering out classroom interaction and casual content, generating condensed versions and course outlines.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Node.js 22 | Script execution |
| Python | 3.11+ | PPT OCR processing |
| ASR | DashScope paraformer-v2 | Speech recognition |
| OCR | DashScope VL | PPT text extraction |
| TTS | DashScope CosyVoice / Edge TTS | Voice generation |
| Video | FFmpeg | Audio extraction, frame detection, editing |

## Directory Structure

```
condense-video/
├── SKILL.md              # Main skill definition and workflow documentation
├── .env                  # API keys (DASHSCOPE_API_KEY)
├── scripts/              # Implementation scripts
│   ├── dashscope_transcribe.js    # ASR transcription entry point
│   ├── config.json                # Configuration (OCR, classification, cutting)
│   ├── requirements.txt           # Python dependencies
│   ├── venv/                      # Python virtual environment
│   └── lib/                       # Shared utilities
│       ├── fs-utils.js           # File system operations
│       └── path-config.js        # Unified path configuration
└── 规则/                  # Classification and extraction rules (Chinese)
    ├── 1-内容分类.md      # Content classification rules
    ├── 2-结构提取.md      # Chapter structure extraction rules
    ├── 3-总结生成.md      # Summary generation templates
    └── 4-PPT分析.md       # PPT analysis and OCR rules
```

## Core Workflows

### 精要提炼 (Essential Extraction)

Primary workflow for extracting core knowledge from course videos:

```
Video Input
    ↓
[1_转录] ASR Transcription (DashScope paraformer-v2)
    ↓
[5_PPT] Frame Extraction + OCR (DashScope VL)
    ↓
[2_文稿] Content Classification (AI: speech + PPT fusion)
    ↓
Chapter Segmentation (based on PPT switches)
    ↓
Content Summarization (key points extraction)
    ↓
[3_音频] TTS Generation (DashScope CosyVoice / Edge TTS)
    ↓
[4_视频] Smart Cutting (remove non-core content)
    ↓
Output: Condensed video with AI voiceover + course outline
```

### 精讲重构 (Detailed Reconstruction)

Secondary workflow for restructuring course content (shares infrastructure).

## Data Flow

```
Input: lecture.mp4
    ├─→ Audio → ASR → transcript.json
    ├─→ Video → Frame Detection → images/ → OCR → ocr_result.json
    └─→ Metadata (duration, fps)

transcript.json + ocr_result.json
    ↓
AI Classification (DashScope LLM)
    ↓
segments.json (with labels: core/explain/interact/chat/transition)

segments.json
    ↓
Chapter Detection + Summarization
    ↓
outline.md + condensed.txt

condensed.txt → TTS → tts_audio.mp3
segments.json + original video → FFmpeg editing
    ↓
condensed_course.mp4 (final output)
```

## Step Number Convention

Unified step numbering across workflows:

| Step | Directory | Purpose |
|------|-----------|---------|
| 1_转录 | steps/1_转录 | ASR transcription |
| 2_文稿 | steps/2_文稿 | Script processing (classify, extract) |
| 3_音频 | steps/3_音频 | Audio generation (TTS) |
| 4_视频 | steps/4_视频 | Video editing and composition |
| 5_PPT | steps/5_PPT | PPT frames and OCR |

## Output Directory Structure

```
output/
└── YYYY-MM-DD_视频名/
    └── 精要提炼/
        └── steps/
            ├── 1_转录/
            ├── 2_文稿/
            ├── 3_音频/
            ├── 4_视频/
            │   └── condensed_course.mp4
            └── 5_PPT/
```

## Classification Labels

| Label | Description | Action |
|-------|-------------|--------|
| core | Core knowledge (definitions, formulas) | Keep |
| explain | Explanations, examples | Optional |
| interact | Classroom interaction | Delete |
| chat | Off-topic chat | Delete |
| transition | Transition phrases | Delete |
