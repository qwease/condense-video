# Backend - condense-video

**Last Updated**: 2026-02-27

## Script Architecture

This is a Node.js + Python hybrid skill. JavaScript handles orchestration and API calls, Python handles image processing.

## Entry Points

| Script | Purpose | CLI Usage |
|--------|---------|-----------|
| `dashscope_transcribe.js` | ASR transcription | `node dashscope_transcribe.js <audio_url> [-o output]` |

## Library Modules

### `lib/fs-utils.js`

File system utilities with Windows path compatibility.

```javascript
// Key exports
module.exports = {
  normalizeForFFmpeg(filePath)    // Convert backslashes for FFmpeg
  readJSONSafe(filePath, default)  // Safe JSON parsing
  writeJSONSafe(filePath, data)    // Safe JSON writing with dir creation
  ensureDir(dirPath)               // Recursive directory creation
  emptyDir(dirPath, deleteSelf)    // Clear directory contents
  findFiles(dirPath, pattern)      // Glob-like file finding
  processFiles(files, processor, options)  // Batch async processing
}
```

### `lib/path-config.js`

Unified path configuration for all workflows.

```javascript
// Core exports
module.exports = {
  createWorkflowPaths(videoPath, workflowName, options)
  ensureDirectories(paths, stepNames)
  getDisplayPath(fullPath, basePath)
  findExistingWorkflow(videoPath, workflowName)
  STEP_NUMBERS  // { TRANSCRIBE: '1_转录', SCRIPT: '2_文稿', ... }
}
```

## Workflow Paths Structure

```javascript
{
  sessionName: "2026-02-27_lecture",
  workflowName: "精要提炼",
  input: { video: "/path/to/video.mp4", videoName: "lecture" },
  output: { root: "/output/.../精要提炼", base: "/output", session: "/output/2026-02-27_lecture" },
  steps: {
    "1_转录": "/output/.../steps/1_转录",
    "2_文稿": "/output/.../steps/2_文稿",
    "3_音频": "/output/.../steps/3_音频",
    "4_视频": "/output/.../steps/4_视频",
    "5_PPT": "/output/.../steps/5_PPT"
  },
  transcribe: { audio: "...", result: "...", converted: "..." },
  ppt: { frames: "...", images: "...", ocrResult: "..." },
  classify: { input: "...", result: "...", report: "..." },
  audio: { dir: "...", timing: "..." },
  resultVideo: "...",
  outline: "..."
}
```

## Configuration

### `config.json`

```json
{
  "name": "videocut:精要提炼",
  "version": "1.0.0",

  "ocr": {
    "provider": "dashscope",
    "model": "qwen3.5-plus",
    "concurrency": 5
  },

  "classification": {
    "provider": "dashscope",
    "model": "qwen-plus",
    "concurrency": 10,
    "batchSize": 50
  },

  "frameExtraction": {
    "sceneThreshold": 0.3,
    "minInterval": 2,
    "maxWidth": 1920
  },

  "cutting": {
    "modes": {
      "essential": { "deleteLabels": ["interact", "chat", "transition"] },
      "complete": { "deleteLabels": ["chat"] }
    }
  }
}
```

## External APIs

### DashScope (Aliyun)

| Service | Model | Purpose |
|---------|-------|---------|
| ASR | paraformer-v2 | Speech recognition |
| OCR | qwen3.5-plus | PPT text extraction |
| LLM | qwen-plus | Content classification |
| TTS | qwen3-tts-flash | Voice generation |

### Environment Variables

```bash
DASHSCOPE_API_KEY=sk-xxx  # Required for all DashScope services
```

## Python Dependencies

```
opencv-python>=0.4.0     # Image processing
Pillow>=9.0.0            # Image I/O
imagehash>=4.3.0         # Frame difference detection
```

## Process Flow

### 1. Transcription Phase
```bash
ffmpeg -i video.mp4 -vn audio.mp3
curl -F "files[]=@audio.mp3" https://uguu.se/upload  # Get public URL
node dashscope_transcribe.js <url>  # ASR via DashScope
```

### 2. PPT Extraction Phase
```bash
ffmpeg -i video.mp4 -vf "select='gt(scene,0.3)'" frames/
python ocr_slides.py frames/ --output ocr_result.json
```

### 3. Classification Phase
```javascript
// AI classification with speech + PPT fusion
DashScope LLM → segments.json with labels
```

### 4. TTS + Editing Phase
```bash
node generate_tts.js --input condensed.json --engine dashscope
ffmpeg -i segments.mp4 -i tts.mp3 -c:v copy -c:a aac output.mp4
```
