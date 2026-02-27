# 进度记录: Phase 3 - 工具层实现

**日期**: 2026-02-27
**状态**: 已完成
**完成度**: 100%

---

## 已完成

### 3.1 FFmpeg 封装 (utils/ffmpeg.py)
- [x] 实现 `run_ffmpeg()` - FFmpeg 命令异步执行
- [x] 实现 `extract_audio()` - 音频提取
- [x] 实现 `extract_frames()` - 关键帧提取 (基于场景变化)
- [x] 实现 `concat_videos()` - 视频合并
- [x] 实现 `merge_audio_video()` - 音视频合成
- [x] 实现 `cut_video()` - 视频剪裁
- [x] 实现 `get_video_info()` - 视频信息获取
- [x] 实现 `resize_video()` - 视频尺寸调整
- [x] 实现 `convert_format()` - 格式转换
- [x] 实现 `check_ffmpeg_installed()` - FFmpeg 安装检查
- [x] 实现 `get_ffmpeg_version()` - FFmpeg 版本获取

**设计决策**:
- 使用 `asyncio.create_subprocess_exec` 实现异步执行
- 支持超时控制 (默认 3600 秒)
- 场景检测阈值设为 0.3 (可调)
- 支持多种视频合并方法 (concat/filter)

### 3.2 视频工具 (utils/video.py)
- [x] 实现 `TimeRange` 数据类 - 时间范围表示
- [x] 实现 `VideoSegment` 数据类 - 视频片段表示
- [x] 实现 `Chapter` 数据类 - 章节表示
- [x] 实现 `calculate_segment_time_ranges()` - 根据转录计算时间范围
- [x] 实现 `filter_segments_by_classification()` - 基于分类过滤片段
- [x] 实现 `merge_time_ranges()` - 合并时间范围
- [x] 实现 `generate_timeline()` - 生成剪辑时间轴
- [x] 实现 `get_video_summary()` - 获取视频摘要
- [x] 实现 `calculate_cut_statistics()` - 计算剪辑统计
- [x] 实现 `classify_to_segments()` - 分类结果转片段
- [x] 实现 `create_cut_list()` - 创建剪辑列表

**设计决策**:
- 使用 dataclass 简化数据结构
- 支持相邻片段自动合并 (默认 2 秒阈值)
- 提供剪辑统计 (压缩比、保留率等)
- 时间范围支持重叠检测

### 3.3 时间工具 (utils/time.py)
- [x] 实现 `TimeStamp` 数据类 - 时间戳表示
- [x] 实现 `seconds_to_hms()` - 秒转 HH:MM:SS
- [x] 实现 `seconds_to_hms_ms()` - 秒转 HH:MM:SS.mmm
- [x] 实现 `hms_to_seconds()` - HH:MM:SS 转秒
- [x] 实现 `frames_to_seconds()` - 帧号转秒
- [x] 实现 `seconds_to_frames()` - 秒转帧号
- [x] 实现 `validate_time_range()` - 时间范围验证
- [x] 实现 `format_duration()` - 时长格式化
- [x] 实现 `parse_duration_string()` - 解析时长字符串
- [x] 实现 `calculate_overlap()` - 计算重叠时长
- [x] 实现 `merge_overlapping_ranges()` - 合并重叠范围
- [x] 实现 `split_range_by_points()` - 按点分割范围
- [x] 实现 `align_to_frame()` - 对齐到帧边界

**设计决策**:
- 支持多种时间格式 (FFmpeg, SRT, WebVTT)
- 帧边界对齐支持向上/向下/最近
- 时间格式使用正则表达式解析
- 提供时长可读格式化

### 3.4 文本工具 (utils/text.py)
- [x] 实现 `clean_text()` - 文本清理
- [x] 实现 `split_by_punctuation()` - 按标点分句
- [x] 实现 `split_by_silence()` - 按静音分句
- [x] 实现 `smart_sentence_split()` - 智能分句 (标点+静音)
- [x] 实现 `is_filler_sentence()` - 填充句检测
- [x] 实现 `is_interaction()` - 互动内容检测
- [x] 实现 `is_transition()` - 过渡语检测
- [x] 实现 `extract_keywords()` - 关键词提取
- [x] 实现 `merge_sentences()` - 合并短句
- [x] 实现 `format_sentence_index()` - 格式化句子索引
- [x] 实现 `parse_sentence_index()` - 解析句子索引
- [x] 实现 `create_condensed_text()` - 创建浓缩文本
- [x] 实现 `truncate_for_tts()` - TTS 文本截断
- [x] 实现 `extract_formulas()` - 提取公式
- [x] 实现 `extract_definitions()` - 提取定义

**设计决策**:
- 智能分句结合标点和静音 (0.5 秒阈值)
- 支持语气词、互动关键词、过渡语检测
- TTS 截断支持按句子或强制分割
- 关键词提取使用简单词频统计

---

## 进行中

**无** - Phase 3 已完成

---

## 待完成

### Phase 4: Celery 任务实现
- [ ] 实现 `tasks/video/download.py` - 视频下载/接收
- [ ] 实现 `tasks/video/audio_extract.py` - 音频提取
- [ ] 实现 `tasks/asr/transcribe.py` - ASR 转录
- [ ] 实现 `tasks/ppt/extract.py` - PPT 关键帧提取
- [ ] 实现 `tasks/ppt/ocr.py` - PPT OCR 识别
- [ ] 实现 `tasks/llm/classify.py` - 内容分类
- [ ] 实现 `tasks/llm/segment.py` - 章节切分
- [ ] 实现 `tasks/llm/summarize.py` - 内容总结
- [ ] 实现 `tasks/tts/generate.py` - TTS 生成
- [ ] 实现 `tasks/workflows.py` - 工作流编排

---

## 问题与解决方案

### 问题 002: Python 环境下视频处理库选择

**日期**: 2026-02-27
**来源**: 技术选型

**问题**: Python 原生视频处理能力有限，需要依赖外部工具。

**解决方案**:
- FFmpeg 通过 subprocess 调用，稳定可靠
- 暂不使用 PyAV (ffmpeg-python 的底层库)，避免编译问题
- OpenCV 用于高级帧处理 (如感知哈希)，可按需集成

**实施状态**: ✅ 已完成

---

## 文件清单

### 新创建的文件

| 文件路径 | 说明 |
|----------|------|
| `utils/ffmpeg.py` | FFmpeg 命令异步封装 |
| `utils/video.py` | 视频处理高级工具 |
| `utils/time.py` | 时间处理工具 |
| `utils/text.py` | 文本处理工具 |

---

## 设计决策

### 决策 003: 使用 dataclass 定义数据结构

**日期**: 2026-02-27
**来源**: Python 最佳实践

**内容**: 使用 `@dataclass` 定义 `TimeRange`, `VideoSegment`, `Chapter` 等数据结构

**原因**:
- 自动生成 `__init__`, `__repr__`, `__eq__` 等方法
- 支持类型注解
- 代码简洁易读
- 与 Pydantic 模型兼容良好

**实施方案**:
```python
@dataclass
class VideoSegment:
    index: int
    time_range: TimeRange
    text: str
    classification: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

### 决策 004: 智能分句结合标点和静音

**日期**: 2026-02-27
**来源**: 参考原 JS 实现

**内容**: 句子分割同时考虑标点符号和静音间隔

**原因**:
- 纯标点分割可能导致句子过长
- 纯静音分割可能在非句子边界分割
- 两者结合可以得到更合理的句子划分

**实施方案**:
- 遇到 `。！？.!?!` 等标点时分句
- 静音间隔 >= 0.5 秒时分句
- 优先按标点分句，标点间距过长时按静音补充

---

## 下一步计划

1. 实现 Phase 4.1: 视频处理任务 (download, audio_extract)
2. 实现 Phase 4.2: ASR 转录任务
3. 实现 Phase 4.3: PPT 处理任务 (extract, ocr)
4. 实现 Phase 4.4: LLM 处理任务 (classify, segment, summarize)

**预计完成时间**: 2026-02-27

---

## 验证标准

- [x] 所有文件已创建
- [x] 代码符合 Python 最佳实践
- [x] 类型注解完整
- [x] 文档字符串完整
- [x] FFmpeg 封装支持所有必要操作
- [x] 视频工具支持时间范围、片段过滤
- [x] 时间工具支持多种格式转换
- [x] 文本工具支持智能分句和浓缩
