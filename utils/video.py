"""
视频处理工具模块

提供视频处理的高级功能：
- 视频片段时间范围计算
- 基于分类的片段过滤
- PPT 关键帧提取
- 时间轴生成
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging import setup_logging
from utils.ffmpeg import get_video_info

logger = setup_logging()


@dataclass
class TimeRange:
    """时间范围"""

    start: float
    end: float

    @property
    def duration(self) -> float:
        """时间范围长度"""
        return max(0, self.end - self.start)

    def overlaps(self, other: "TimeRange") -> bool:
        """检查与另一个时间范围是否重叠"""
        return not (self.end < other.start or self.start > other.end)

    def contains(self, timestamp: float) -> bool:
        """检查是否包含某个时间点"""
        return self.start <= timestamp <= self.end

    def to_dict(self) -> dict[str, float]:
        """转换为字典"""
        return {"start": self.start, "end": self.end, "duration": self.duration}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimeRange":
        """从字典创建"""
        return cls(start=data["start"], end=data["end"])


@dataclass
class VideoSegment:
    """视频片段"""

    index: int
    time_range: TimeRange
    text: str
    classification: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def start(self) -> float:
        """开始时间"""
        return self.time_range.start

    @property
    def end(self) -> float:
        """结束时间"""
        return self.time_range.end

    @property
    def duration(self) -> float:
        """片段时长"""
        return self.time_range.duration

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "text": self.text,
            "classification": self.classification,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoSegment":
        """从字典创建"""
        time_range = TimeRange(
            start=data["start"], end=data["end"]
        )
        return cls(
            index=data["index"],
            time_range=time_range,
            text=data["text"],
            classification=data["classification"],
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Chapter:
    """章节"""

    id: int
    title: str
    time_range: TimeRange
    segments: list[VideoSegment] = field(default_factory=list)
    ppt_slides: list[int] = field(default_factory=list)
    key_formulas: list[str] = field(default_factory=list)

    @property
    def start(self) -> float:
        """开始时间"""
        return self.time_range.start

    @property
    def end(self) -> float:
        """结束时间"""
        return self.time_range.end

    @property
    def duration(self) -> float:
        """章节时长"""
        return self.time_range.duration

    @property
    def core_count(self) -> int:
        """核心内容片段数量"""
        return sum(1 for s in self.segments if s.classification == "core")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "segments": [s.to_dict() for s in self.segments],
            "pptSlides": self.ppt_slides,
            "keyFormulas": self.key_formulas,
            "coreCount": self.core_count,
        }


async def calculate_segment_time_ranges(
    transcript_path: str,
    video_duration: float | None = None,
) -> list[TimeRange]:
    """
    根据转录文件计算句子时间范围

    Args:
        transcript_path: 转录文件路径 (sentences.txt)
        video_duration: 视频总时长（可选，用于验证）

    Returns:
        时间范围列表
    """
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"转录文件不存在: {transcript_path}")

    time_ranges = []

    # 读取 sentences.txt 格式: idx|startIdx-endIdx|text
    # 或读取 subtitles_words.json 获取精确时间戳
    sentences_file = path.parent / "sentences.txt"
    subtitles_file = path.parent / "subtitles_words.json"

    if subtitles_file.exists():
        # 从字级别字幕计算句子时间范围
        with open(subtitles_file, "r", encoding="utf-8") as f:
            subtitles = json.load(f)

        # 按句子分组计算时间范围
        words = subtitles.get("words", [])
        current_sentence_words = []
        sentence_boundaries = []

        for word in words:
            current_sentence_words.append(word)
            # 检测句子结束（标点或长静音）
            text = word.get("text", "")
            if text and text[-1] in "。！？.!?" or word.get("silence", False):
                if current_sentence_words:
                    start = current_sentence_words[0].get("start_time", 0)
                    end = current_sentence_words[-1].get("end_time", 0)
                    sentence_boundaries.append((start, end))
                    current_sentence_words = []

        # 处理剩余
        if current_sentence_words:
            start = current_sentence_words[0].get("start_time", 0)
            end = current_sentence_words[-1].get("end_time", 0)
            sentence_boundaries.append((start, end))

        time_ranges = [TimeRange(start=s, end=e) for s, e in sentence_boundaries]

    elif sentences_file.exists():
        # 从 sentences.txt 解析时间范围
        # 格式: idx|startIdx-endIdx|text
        # 需要结合原始字幕获取时间
        with open(sentences_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 这里简化处理，实际需要结合原始字幕
        # 暂时使用索引估算时间
        for line in lines:
            if "|" in line:
                parts = line.strip().split("|")
                if len(parts) >= 2:
                    # 解析 startIdx-endIdx
                    idx_range = parts[1]
                    if "-" in idx_range:
                        try:
                            start_idx = int(idx_range.split("-")[0])
                            # 简化估算：假设每个字约 0.3 秒
                            start = start_idx * 0.3
                            # 从 text 长度估算持续时间
                            text = parts[2] if len(parts) > 2 else ""
                            duration = len(text) * 0.15
                            time_ranges.append(TimeRange(start=start, end=start + duration))
                        except (ValueError, IndexError):
                            continue

    else:
        raise FileNotFoundError(f"找不到转录数据文件: {sentences_file} 或 {subtitles_file}")

    # 验证时间范围
    if video_duration:
        for tr in time_ranges:
            if tr.end > video_duration:
                logger.warning(
                    f"时间范围超出视频长度: {tr.end} > {video_duration}"
                )

    logger.info(f"计算了 {len(time_ranges)} 个时间范围")
    return time_ranges


def filter_segments_by_classification(
    segments: list[VideoSegment],
    keep_classes: set[str],
    merge_gap: float = 2.0,
) -> list[VideoSegment]:
    """
    根据分类过滤视频片段

    Args:
        segments: 视频片段列表
        keep_classes: 要保留的分类标签集合
        merge_gap: 合并间隔小于此值的相邻片段（秒）

    Returns:
        过滤后的片段列表
    """
    # 过滤
    filtered = [s for s in segments if s.classification in keep_classes]

    if not filtered:
        return []

    # 按时间排序
    filtered.sort(key=lambda s: s.start)

    # 合并相邻片段
    if merge_gap > 0:
        merged = []
        current = filtered[0]

        for segment in filtered[1:]:
            # 检查是否需要合并
            if segment.start - current.end <= merge_gap:
                # 合并片段
                merged_text = f"{current.text} {segment.text}"
                merged_range = TimeRange(
                    start=current.start,
                    end=segment.end
                )
                # 合并元数据
                merged_metadata = {
                    **current.metadata,
                    "merged_count": current.metadata.get("merged_count", 1) + 1,
                }

                current = VideoSegment(
                    index=current.index,
                    time_range=merged_range,
                    text=merged_text,
                    classification=current.classification,
                    confidence=min(current.confidence, segment.confidence),
                    metadata=merged_metadata,
                )
            else:
                merged.append(current)
                current = segment

        merged.append(current)
        filtered = merged

    logger.info(
        f"过滤片段: {len(segments)} -> {len(filtered)} "
        f"(保留分类: {', '.join(keep_classes)})"
    )
    return filtered


async def merge_time_ranges(
    ranges: list[TimeRange],
    gap_threshold: float = 2.0,
) -> list[TimeRange]:
    """
    合并相邻或重叠的时间范围

    Args:
        ranges: 时间范围列表
        gap_threshold: 间隔小于此值则合并（秒）

    Returns:
        合并后的时间范围列表
    """
    if not ranges:
        return []

    # 按开始时间排序
    sorted_ranges = sorted(ranges, key=lambda r: r.start)

    merged = []
    current = sorted_ranges[0]

    for rng in sorted_ranges[1:]:
        # 检查重叠或间隔
        if rng.start - current.end <= gap_threshold:
            # 合并
            current = TimeRange(
                start=current.start,
                end=max(current.end, rng.end)
            )
        else:
            merged.append(current)
            current = rng

    merged.append(current)

    logger.info(f"合并时间范围: {len(ranges)} -> {len(merged)}")
    return merged


def generate_timeline(
    segments: list[VideoSegment],
    fps: float = 25.0,
) -> list[dict[str, Any]]:
    """
    生成视频剪辑时间轴

    Args:
        segments: 视频片段列表
        fps: 帧率

    Returns:
        时间轴数据列表
    """
    timeline = []

    for seg in segments:
        start_frame = int(seg.start * fps)
        end_frame = int(seg.end * fps)

        timeline.append({
            "segment_index": seg.index,
            "start_time": seg.start,
            "end_time": seg.end,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "duration": seg.duration,
            "text": seg.text,
            "classification": seg.classification,
        })

    return timeline


async def get_video_summary(video_path: str) -> dict[str, Any]:
    """
    获取视频摘要信息

    Args:
        video_path: 视频文件路径

    Returns:
        视频摘要信息
    """
    info = await get_video_info(video_path)

    # 计算额外信息
    duration_minutes = info["duration"] / 60
    estimated_size_mb = Path(video_path).stat().st_size / (1024 * 1024)

    summary = {
        **info,
        "duration_minutes": round(duration_minutes, 2),
        "size_mb": round(estimated_size_mb, 2),
        "aspect_ratio": round(info["width"] / info["height"], 2) if info["height"] > 0 else 0,
    }

    return summary


def calculate_cut_statistics(
    original_segments: list[VideoSegment],
    filtered_segments: list[VideoSegment],
) -> dict[str, Any]:
    """
    计算剪辑统计信息

    Args:
        original_segments: 原始片段列表
        filtered_segments: 过滤后片段列表

    Returns:
        剪辑统计信息
    """
    if not original_segments:
        return {
            "original_duration": 0,
            "filtered_duration": 0,
            "removed_duration": 0,
            "retention_ratio": 0,
            "compression_ratio": 0,
            "segment_count": {"original": 0, "filtered": 0},
        }

    original_duration = sum(s.duration for s in original_segments)
    filtered_duration = sum(s.duration for s in filtered_segments)
    removed_duration = original_duration - filtered_duration

    stats = {
        "original_duration": round(original_duration, 2),
        "filtered_duration": round(filtered_duration, 2),
        "removed_duration": round(removed_duration, 2),
        "retention_ratio": round(
            (filtered_duration / original_duration * 100) if original_duration > 0 else 0,
            2
        ),
        "compression_ratio": round(
            (removed_duration / original_duration * 100) if original_duration > 0 else 0,
            2
        ),
        "segment_count": {
            "original": len(original_segments),
            "filtered": len(filtered_segments),
        },
    }

    return stats


def classify_to_segments(
    classification_result: dict[str, Any],
    time_ranges: list[TimeRange],
) -> list[VideoSegment]:
    """
    将分类结果转换为视频片段列表

    Args:
        classification_result: 分类结果 (包含 segments.json 数据)
        time_ranges: 时间范围列表

    Returns:
        视频片段列表
    """
    segments = []

    for idx, time_range in enumerate(time_ranges):
        # 从分类结果获取对应索引的分类
        # 这里需要根据实际的分类结果格式调整
        classification_data = classification_result.get("classifications", [])

        if idx < len(classification_data):
            cls_data = classification_data[idx]
            segment = VideoSegment(
                index=idx,
                time_range=time_range,
                text=cls_data.get("text", ""),
                classification=cls_data.get("label", "unknown"),
                confidence=cls_data.get("confidence", 1.0),
                metadata={
                    "reasoning": cls_data.get("reasoning", ""),
                },
            )
        else:
            # 默认分类
            segment = VideoSegment(
                index=idx,
                time_range=time_range,
                text="",
                classification="unknown",
                metadata={},
            )

        segments.append(segment)

    return segments


async def create_cut_list(
    segments: list[VideoSegment],
    video_info: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    创建 FFmpeg 剪辑列表

    Args:
        segments: 要保留的视频片段列表
        video_info: 视频信息

    Returns:
        剪辑命令列表
    """
    cut_list = []

    for seg in segments:
        cut_list.append({
            "start": seg.start,
            "end": seg.end,
            "duration": seg.duration,
            "text": seg.text,
            "classification": seg.classification,
        })

    return cut_list
