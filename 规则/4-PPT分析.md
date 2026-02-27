<!--
input: 视频文件
output: slides.json (结构化的PPT数据)
pos: 规则，PPT关键帧提取和OCR识别的依据

架构守护者：一旦我被修改，请同步更新：
1. 所属文件夹的 README.md
-->

# PPT 分析规则

## 结构化输出

### slides.json 格式

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
    },
    {
      "frameId": 2,
      "framePath": "frames/frame_0002.jpg",
      "timestamp": 45.2,
      "ocrText": "传递函数\nG(s) = Y(s)/R(s)\n\n零初始条件下，输出与输入的拉氏变换之比",
      "structure": {
        "title": "传递函数",
        "subtitles": [],
        "body": ["零初始条件下，输出与输入的拉氏变换之比"],
        "formulas": ["G(s) = Y(s)/R(s)"],
        "keyTerms": ["传递函数", "拉氏变换", "零初始条件"],
        "confidence": 0.95
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

## 时间戳估算

由于 FFmpeg 场景检测输出的帧没有精确时间戳，需要估算：

```python
def estimate_timestamps(frames, video_duration, total_frames):
    """
    估算每帧的时间戳
    """
    for i, frame in enumerate(frames):
        # 假设帧在视频中均匀分布
        frame['timestamp'] = (i / len(frames)) * video_duration

    return frames
```

更精确的方法是使用 FFmpeg 输出带时间戳的信息：

```bash
ffmpeg -i video.mp4 \
  -vf "select='gt(scene,0.3)',showinfo" \
  -vsync vfr frames/frame_%04d.jpg 2>&1 | grep "pts_time"
```

## 常见问题

### Q: PPT 动画导致提取过多帧？

调高场景切换阈值，或使用时间采样补充：

```bash
# 先场景检测，再每 30 秒采样
ffmpeg -i video.mp4 -vf "select='gt(scene,0.4)'" -vsync vfr frames/frame_%04d.jpg
ffmpeg -i video.mp4 -vf "fps=1/30" frames/sample_%04d.jpg
```

### Q: OCR 识别中文公式混乱？

公式部分使用专门的 OCR（如 Mathpix），或手动标注：

```json
{
  "formulas": ["G(s) = Y(s)/R(s)"],
  "formulaImages": ["frames/formula_001.jpg"],
  "needsManualReview": true
}
```

### Q: PPT 标题识别不准确？

结合多种特征判断：
1. 位置（顶部）
2. 字体大小
3. 居中对齐
4. 包含章节词（"第X章"）

## 与语音对齐

```python
def align_ppt_speech(slides, sentences):
    """
    将 PPT 内容与语音对齐
    """
    for slide in slides:
        timestamp = slide['timestamp']

        # 找到对应时间段的句子
        matching_sentences = [
            s for s in sentences
            if s['start_time'] >= timestamp and
               s['start_time'] < timestamp + 60  # 1 分钟窗口
        ]

        slide['speechSegments'] = matching_sentences

        # 交叉验证内容相关性
        slide['relevance'] = calculate_relevance(
            slide['ocrText'],
            ' '.join(s['text'] for s in matching_sentences)
        )

    return slides
```
