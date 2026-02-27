"""
视频剪辑任务

根据分类结果剪辑视频，保留核心内容。
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.redis_client import update_progress
from utils.ffmpeg import concat_videos, cut_video, get_video_info
from utils.video import (
    TimeRange,
    VideoSegment,
    calculate_cut_statistics,
    filter_segments_by_classification,
)

logger = setup_logging()


class VideoEditError(VideoProcessingException):
    """视频剪辑错误"""
    pass


@shared_task(
    name="tasks.video.edit",
    bind=True,
    max_retries=2,
)
def edit_video(
    self,
    task_id: str,
    video_path: str,
    classification_file: str,
    output_dir: str,
    mode: str = "essential",
) -> dict[str, Any]:
    """
    根据分类结果剪辑视频

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 原始视频路径
        classification_file: 分类结果文件 (classification.json)
        output_dir: 输出目录
        mode: 剪辑模式 (essential, complete)

    Returns:
        剪辑结果

    Raises:
        VideoEditError: 剪辑失败
    """
    logger.info(f"开始视频剪辑: mode={mode}")

    update_progress(
        task_id,
        ProgressStep.VIDEO_EDIT,
        0.0,
        "正在分析视频内容...",
    )

    try:
        # 获取剪辑模式配置
        cutting_modes = settings.cutting_modes
        if mode not in cutting_modes:
            raise VideoEditError(f"Unknown cutting mode: {mode}")

        delete_labels = cutting_modes[mode]["delete_labels"]

        # 读取分类结果
        class_file = Path(classification_file)
        if not class_file.exists():
            raise VideoEditError(f"分类文件不存在: {classification_file}")

        with open(class_file, "r", encoding="utf-8") as f:
            classification_data = json.load(f)

        # 读取转录数据获取时间戳
        transcript_file = class_file.parent / "sentences.txt"
        if not transcript_file.exists():
            raise VideoEditError(f"转录文件不存在: {transcript_file}")

        # 构建视频片段列表
        segments = _build_segments_from_classification(
            classification_data,
            transcript_file,
        )

        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.2,
            f"正在过滤片段 (模式: {mode})...",
        )

        # 根据模式过滤片段
        keep_classes = [
            label for label in ["core", "explain", "interact", "chat", "transition"]
            if label not in delete_labels
        ]

        filtered_segments = filter_segments_by_classification(
            segments=segments,
            keep_classes=set(keep_classes),
            merge_gap=settings.cutting_buffer_ms / 1000.0,  # 转换为秒
        )

        if not filtered_segments:
            raise VideoEditError("没有符合条件的片段，无法生成视频")

        # 计算统计信息
        stats = calculate_cut_statistics(segments, filtered_segments)

        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.4,
            f"正在剪辑视频 (保留 {stats['filtered_duration']:.1f}秒 / {stats['original_duration']:.1f}秒)...",
        )

        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        temp_dir = output_path / "temp"
        temp_dir.mkdir(exist_ok=True)

        # 方案: 使用 FFmpeg concat filter 合并片段
        condensed_video = asyncio.run(_create_condensed_video(
            video_path=video_path,
            segments=filtered_segments,
            output_dir=str(temp_dir),
            final_output=str(output_path / "condensed_course.mp4"),
        ))

        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.9,
            "视频剪辑完成",
        )

        # 保存剪辑列表
        cut_list_file = output_path / "cut_list.json"
        with open(cut_list_file, "w", encoding="utf-8") as f:
            json.dump({
                "mode": mode,
                "delete_labels": delete_labels,
                "segments": [s.to_dict() for s in filtered_segments],
                "statistics": stats,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"视频剪辑完成: {len(filtered_segments)} 个片段, 压缩率 {stats['compression_ratio']}%")

        return {
            "success": True,
            "condensed_video": condensed_video,
            "cut_list": str(cut_list_file),
            "statistics": stats,
            "segment_count": len(filtered_segments),
        }

    except Exception as e:
        logger.error(f"视频剪辑时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.0,
            f"视频剪辑失败: {str(e)}",
        )
        raise VideoEditError(f"视频剪辑失败: {e}") from e


def _build_segments_from_classification(
    classification_data: dict[str, Any],
    transcript_file: Path,
) -> list[VideoSegment]:
    """
    从分类结果和转录文件构建视频片段列表

    Args:
        classification_data: 分类结果数据
        transcript_file: 转录文件路径

    Returns:
        视频片段列表
    """
    segments = []

    # 读取转录时间戳
    with open(transcript_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 解析转录文件获取时间戳
    # 格式: idx|startIdx-endIdx|text
    # 需要结合 subtitles_words.json 获取精确时间
    subtitles_file = transcript_file.parent / "subtitles_words.json"

    if subtitles_file.exists():
        with open(subtitles_file, "r", encoding="utf-8") as f:
            subtitles = json.load(f)

        words = subtitles.get("subtitles_words", subtitles.get("words", []))

        # 构建句子索引到时间的映射
        sentence_boundaries = _extract_sentence_boundaries(words)

    # 从分类数据获取片段
    for idx, seg_data in enumerate(classification_data.get("segments", [])):
        time_range = TimeRange(
            start=seg_data.get("start_time", 0.0),
            end=seg_data.get("end_time", 0.0),
        )

        segment = VideoSegment(
            index=idx,
            time_range=time_range,
            text=seg_data.get("text", ""),
            classification=seg_data.get("label", "unknown"),
            confidence=seg_data.get("confidence", 1.0),
            metadata={"reason": seg_data.get("reason", "")},
        )
        segments.append(segment)

    return segments


def _extract_sentence_boundaries(words: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """
    从字级别字幕提取句子边界

    Args:
        words: 字级别字幕列表

    Returns:
        [(start, end), ...] 句子边界列表
    """
    boundaries = []
    current_start = 0.0
    current_words = []

    for word in words:
        text = word.get("text", "")
        start_time = word.get("start", word.get("start_time", 0))
        end_time = word.get("end", word.get("end_time", 0))

        if not current_words:
            current_start = start_time

        current_words.append(word)

        # 句子结束条件: 标点或静音
        if text and text[-1] in "。！？.!?" or word.get("silence", False):
            boundaries.append((current_start, end_time))
            current_words = []
            current_start = 0.0

    # 处理剩余
    if current_words:
        boundaries.append((current_start, current_words[-1].get("end", current_words[-1].get("end_time", 0))))

    return boundaries


async def _create_condensed_video(
    video_path: str,
    segments: list[VideoSegment],
    output_dir: str,
    final_output: str,
) -> str:
    """
    创建浓缩视频

    Args:
        video_path: 原始视频路径
        segments: 要保留的片段列表
        output_dir: 临时输出目录
        final_output: 最终输出路径

    Returns:
        浓缩视频路径
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 获取视频信息
    video_info = await get_video_info(video_path)

    # 如果只有一个片段，直接裁剪
    if len(segments) == 1:
        seg = segments[0]
        return await cut_video(
            video_path=video_path,
            output_path=final_output,
            start_time=seg.start,
            end_time=seg.end,
        )

    # 多个片段: 使用 concat demuxer
    segment_files = []

    for i, seg in enumerate(segments):
        # 添加缓冲时间
        buffer = settings.cutting_buffer_ms / 1000.0
        start = max(0, seg.start - buffer / 2)
        end = min(video_info["duration"], seg.end + buffer / 2)

        segment_file = output_path / f"segment_{i:05d}.mp4"

        await cut_video(
            video_path=video_path,
            output_path=str(segment_file),
            start_time=start,
            end_time=end,
        )

        segment_files.append(str(segment_file))

    # 合并所有片段
    condensed = await concat_videos(
        video_list=segment_files,
        output_path=final_output,
        method="concat",
    )

    return condensed


@shared_task(name="tasks.video.merge_with_audio")
def merge_video_with_audio(
    task_id: str,
    video_path: str,
    audio_path: str,
    output_path: str,
) -> dict[str, Any]:
    """
    将视频与新音频合并

    用于生成带 TTS 配音的浓缩视频。

    Args:
        task_id: 任务 ID
        video_path: 视频路径
        audio_path: 音频路径
        output_path: 输出路径

    Returns:
        合并结果
    """
    from utils.ffmpeg import merge_audio_video

    logger.info(f"合并视频和音频: {video_path} + {audio_path}")

    try:
        result = asyncio.run(merge_audio_video(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_path,
        ))

        return {
            "success": True,
            "output": result,
        }

    except Exception as e:
        logger.error(f"合并视频和音频失败: {e}")
        raise VideoEditError(f"合并失败: {e}") from e
