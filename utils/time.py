"""
时间处理工具模块

提供视频处理中涉及时间的工具函数：
- 时间格式转换
- 时间戳计算
- 时间范围验证
- 时间轴生成
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class TimeStamp:
    """时间戳"""

    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    milliseconds: int = 0

    @property
    def total_seconds(self) -> float:
        """总秒数"""
        return (
            self.hours * 3600
            + self.minutes * 60
            + self.seconds
            + self.milliseconds / 1000
        )

    def to_ffmpeg_format(self) -> str:
        """转换为 FFmpeg 时间格式 (HH:MM:SS.mmm)"""
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}.{self.milliseconds:03d}"

    def to_srt_format(self) -> str:
        """转换为 SRT 字幕时间格式 (HH:MM:SS,mmm)"""
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d},{self.milliseconds:03d}"

    def to_vtt_format(self) -> str:
        """转换为 WebVTT 时间格式 (HH:MM:SS.mmm)"""
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}.{self.milliseconds:03d}"

    @classmethod
    def from_seconds(cls, seconds: float) -> "TimeStamp":
        """从秒数创建"""
        total_ms = int(seconds * 1000)
        hours, remainder = divmod(total_ms, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return cls(hours, minutes, seconds, milliseconds)

    @classmethod
    def from_ffmpeg_format(cls, time_str: str) -> "TimeStamp":
        """从 FFmpeg 时间格式解析"""
        # 格式: HH:MM:SS.mmm 或 HH:MM:SSmmm
        match = re.match(r"(\d{2}):(\d{2}):(\d{2})[.,]?(\d{3})?", time_str)
        if not match:
            raise ValueError(f"无效的时间格式: {time_str}")

        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        milliseconds = int(match.group(4)) if match.group(4) else 0

        return cls(hours, minutes, seconds, milliseconds)

    @classmethod
    def from_srt_format(cls, time_str: str) -> "TimeStamp":
        """从 SRT 时间格式解析 (HH:MM:SS,mmm)"""
        match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", time_str)
        if not match:
            raise ValueError(f"无效的 SRT 时间格式: {time_str}")

        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        milliseconds = int(match.group(4))

        return cls(hours, minutes, seconds, milliseconds)


def seconds_to_hms(seconds: float) -> str:
    """
    将秒数转换为 HH:MM:SS 格式

    Args:
        seconds: 秒数

    Returns:
        HH:MM:SS 格式字符串
    """
    ts = TimeStamp.from_seconds(seconds)
    return f"{ts.hours:02d}:{ts.minutes:02d}:{ts.seconds:02d}"


def seconds_to_hms_ms(seconds: float) -> str:
    """
    将秒数转换为 HH:MM:SS.mmm 格式

    Args:
        seconds: 秒数

    Returns:
        HH:MM:SS.mmm 格式字符串
    """
    return TimeStamp.from_seconds(seconds).to_ffmpeg_format()


def hms_to_seconds(hms: str) -> float:
    """
    将 HH:MM:SS 或 HH:MM:SS.mmm 格式转换为秒数

    Args:
        hms: HH:MM:SS 格式字符串

    Returns:
        秒数
    """
    try:
        ts = TimeStamp.from_ffmpeg_format(hms)
        return ts.total_seconds
    except ValueError:
        # 尝试简单格式 HH:MM:SS
        parts = hms.split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_parts = parts[2].split(".")
            seconds = int(seconds_parts[0])
            milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
            return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
        raise


def frames_to_seconds(
    frame_number: int,
    fps: float,
) -> float:
    """
    将帧号转换为秒数

    Args:
        frame_number: 帧号
        fps: 帧率

    Returns:
        秒数
    """
    return frame_number / fps if fps > 0 else 0


def seconds_to_frames(
    seconds: float,
    fps: float,
) -> int:
    """
    将秒数转换为帧号

    Args:
        seconds: 秒数
        fps: 帧率

    Returns:
        帧号
    """
    return int(seconds * fps) if fps > 0 else 0


def validate_time_range(
    start: float,
    end: float,
    max_duration: float | None = None,
) -> bool:
    """
    验证时间范围是否有效

    Args:
        start: 开始时间（秒）
        end: 结束时间（秒）
        max_duration: 最大允许时长（可选）

    Returns:
        是否有效
    """
    if start < 0 or end < 0:
        return False

    if start >= end:
        return False

    if max_duration is not None:
        if end > max_duration:
            return False

    return True


def format_duration(seconds: float) -> str:
    """
    格式化时长为可读字符串

    Args:
        seconds: 秒数

    Returns:
        格式化的时长字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        remainder = (seconds % 3600) / 60
        return f"{int(hours)}小时{int(remainder)}分钟"


def parse_duration_string(duration_str: str) -> float:
    """
    解析时长字符串为秒数

    Args:
        duration_str: 时长字符串 (如 "1:30", "1:30:45", "90s")

    Returns:
        秒数
    """
    # 格式1: HH:MM:SS 或 MM:SS
    if ":" in duration_str:
        parts = duration_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    # 格式2: 数字 + 单位 (如 "90s", "1.5m", "2h")
    match = re.match(r"([\d.]+)([smh])", duration_str.lower())
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "s":
            return value
        elif unit == "m":
            return value * 60
        elif unit == "h":
            return value * 3600

    # 格式3: 纯数字（秒）
    try:
        return float(duration_str)
    except ValueError:
        raise ValueError(f"无法解析时长字符串: {duration_str}")


def calculate_overlap(
    start1: float,
    end1: float,
    start2: float,
    end2: float,
) -> float:
    """
    计算两个时间范围的重叠长度

    Args:
        start1: 第一个范围的开始
        end1: 第一个范围的结束
        start2: 第二个范围的开始
        end2: 第二个范围的结束

    Returns:
        重叠时长（秒），无重叠返回 0
    """
    overlap_start = max(start1, start2)
    overlap_end = min(end1, end2)

    if overlap_start < overlap_end:
        return overlap_end - overlap_start
    return 0


def merge_overlapping_ranges(
    ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    合并重叠的时间范围

    Args:
        ranges: 时间范围列表 [(start, end), ...]

    Returns:
        合并后的时间范围列表
    """
    if not ranges:
        return []

    # 按开始时间排序
    sorted_ranges = sorted(ranges, key=lambda r: r[0])

    merged = []
    current_start, current_end = sorted_ranges[0]

    for start, end in sorted_ranges[1:]:
        if start <= current_end:
            # 重叠，合并
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    merged.append((current_start, current_end))

    return merged


def split_range_by_points(
    start: float,
    end: float,
    split_points: list[float],
) -> list[tuple[float, float]]:
    """
    根据切分点将时间范围分割为多个子范围

    Args:
        start: 范围开始
        end: 范围结束
        split_points: 切分点列表（必须按升序排列）

    Returns:
        分割后的子范围列表
    """
    # 过滤在范围外的切分点
    valid_points = [p for p in split_points if start < p < end]

    ranges = []
    prev = start

    for point in valid_points:
        ranges.append((prev, point))
        prev = point

    ranges.append((prev, end))

    return ranges


def adjust_timestamps(
    timestamps: list[float],
    offset: float,
    min_value: float = 0,
) -> list[float]:
    """
    调整时间戳（添加偏移量）

    Args:
        timestamps: 时间戳列表
        offset: 偏移量（秒）
        min_value: 最小值限制

    Returns:
        调整后的时间戳列表
    """
    return [max(min_value, t + offset) for t in timestamps]


def round_timestamp(
    timestamp: float,
    precision: int = 3,
) -> float:
    """
    四舍五入时间戳

    Args:
        timestamp: 时间戳
        precision: 小数位数

    Returns:
        四舍五入后的时间戳
    """
    return round(timestamp, precision)


def align_to_frame(
    timestamp: float,
    fps: float,
    direction: str = "nearest",
) -> float:
    """
    将时间戳对齐到帧边界

    Args:
        timestamp: 时间戳
        fps: 帧率
        direction: 对齐方向 ("down", "up", "nearest")

    Returns:
        对齐后的时间戳
    """
    frame_duration = 1 / fps if fps > 0 else 0
    frame_number = timestamp / frame_duration

    if direction == "down":
        aligned_frame = int(frame_number)
    elif direction == "up":
        aligned_frame = int(frame_number) + 1
    else:  # nearest
        aligned_frame = int(frame_number + 0.5)

    return aligned_frame * frame_duration


def calculate_timeline_positions(
    segments: list[dict[str, Any]],
    start_time: float = 0,
) -> list[dict[str, Any]]:
    """
    计算片段在时间轴上的位置（用于生成剪辑后的时间轴）

    Args:
        segments: 片段列表，每个片段包含 start, end, text
        start_time: 起始时间偏移

    Returns:
        包含新时间位置的片段列表
    """
    timeline = []
    current_time = start_time

    for seg in segments:
        duration = seg.get("end", seg["start"]) - seg["start"]

        timeline.append({
            **seg,
            "original_start": seg["start"],
            "original_end": seg.get("end", seg["start"]),
            "new_start": current_time,
            "new_end": current_time + duration,
        })

        current_time += duration

    return timeline
