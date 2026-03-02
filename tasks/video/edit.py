"""
视频剪辑任务

根据分类结果剪辑视频，保留核心内容。
"""

import asyncio
import json
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

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


class EncoderConfig:
    """编码器配置"""
    def __init__(self, name: str, args: str):
        self.name = name
        self.args = args

    def to_list(self) -> list[str]:
        """转换为 FFmpeg 参数列表"""
        return ['-c:v', self.name] + self.args.split()


def detect_encoder() -> EncoderConfig:
    """
    检测可用的硬件加速编码器
    
    优先级:
    1. NVIDIA (h264_nvenc)
    2. Intel QSV (h264_qsv)
    3. AMD AMF (h264_amf)
    4. Apple VideoToolbox (h264_videotoolbox)
    5. 软件编码 (libx264)
    
    Returns:
        编码器配置
    """
    import platform
    
    encoders = []
    
    # Windows 平台
    if platform.system() == 'Windows':
        encoders.extend([
            EncoderConfig('h264_nvenc', '-preset p4 -cq 20'),
            EncoderConfig('h264_qsv', '-global_quality 20'),
            EncoderConfig('h264_amf', '-quality balanced'),
        ])
    # macOS 平台
    elif platform.system() == 'Darwin':
        encoders.append(EncoderConfig('h264_videotoolbox', '-q:v 60'))
    
    # Linux 平台
    elif platform.system() == 'Linux':
        encoders.extend([
            EncoderConfig('h264_nvenc', '-preset p4 -cq 20'),
            EncoderConfig('h264_qsv', '-global_quality 20'),
            EncoderConfig('h264_vaapi', '-qp 20'),
        ])
    
    # 软件编码作为后备
    encoders.append(EncoderConfig('libx264', '-preset fast -crf 18'))
    
    # 检测可用编码器
    for encoder in encoders:
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if encoder.name in result.stdout:
                logger.info(f"🎯 使用编码器: {encoder.name}")
                return encoder
        except Exception as e:
            logger.debug(f"检测编码器 {encoder.name} 失败: {e}")
            continue
    
    # 降级到软件编码
    fallback = EncoderConfig('libx264', '-preset fast -crf 18')
    logger.warning(f"未检测到硬件加速，使用软件编码: {fallback.name}")
    return fallback


@shared_task(
    name="tasks.video.edit",
    bind=True,
    max_retries=2,
)
def edit_video(
    self,
    task_id: str,
    video_path: str,
    frames_info_file: str,
    audio_timing_file: str,
    output_dir: str,
    mode: str = "essential",
) -> dict[str, Any]:
    """
    根据分类结果剪辑视频

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 原始视频路径
        frames_info_file: 帧信息文件 (frames_info.json)
        audio_timing_file: 音频时间文件 (audio_timing.json)
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
        0.85,
        "正在分析视频内容...",
    )

    try:
        # 读取帧信息
        frames_file = Path(frames_info_file)
        if not frames_file.exists():
            raise VideoEditError(f"帧信息文件不存在: {frames_info_file}")

        with open(frames_file, "r", encoding="utf-8") as f:
            frames_data = json.load(f)

        # 读取音频时间文件
        audio_file = Path(audio_timing_file)
        if not audio_file.exists():
            raise VideoEditError(f"音频时间文件不存在: {audio_timing_file}")

        with open(audio_file, "r", encoding="utf-8") as f:
            audio_data = json.load(f)
        
        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.85,
            "已获取PPT帧与音频时间...",
        )

        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        temp_dir = output_path / "temp"
        temp_dir.mkdir(exist_ok=True)

        # 检测编码器
        encoder = detect_encoder()

        # 创建浓缩视频
        condensed_video = asyncio.run(_create_condensed_video(
            task_id=task_id,
            video_path=video_path,
            frames_data=frames_data,
            audio_data=audio_data,
            output_dir=str(temp_dir),
            final_output=str(output_path / "condensed_course.mp4"),
            encoder=encoder,
        ))

        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.95,
            "视频剪辑完成",
        )

        # 清理临时文件
        logger.info("🧹 清理临时文件...")
        shutil.rmtree(temp_dir, ignore_errors=True)

        frames_count = len(frames_data.get("frames", []))
        segments_count = len(audio_data.get("segments", []))
        logger.info(f"✅ 视频剪辑完成: {frames_count} 个帧, {segments_count} 个音频片段")

        return {
            "success": True,
            "condensed_video": condensed_video,
            "encoder": encoder.name,
        }

    except Exception as e:
        logger.error(f"❌ 视频剪辑时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.VIDEO_EDIT,
            0.8,
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
    task_id: str,
    video_path: str,
    frames_data: dict[str, Any],
    audio_data: dict[str, Any],
    output_dir: str,
    final_output: str,
    encoder: EncoderConfig,
    resolution: str = "1920x1080",
    fps: int = 30,
) -> str:
    """
    创建浓缩视频（PPT 图片 + TTS 音频合成）

    Args:
        task_id: 任务 ID
        video_path: 原始视频路径（用于获取视频信息）
        frames_data: 帧数据 (frames_info.json)
        audio_data: 音频数据 (audio_timing.json)
        output_dir: 临时输出目录
        final_output: 最终输出路径
        encoder: 编码器配置
        resolution: 输出分辨率
        fps: 输出帧率

    Returns:
        浓缩视频路径
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    frames = frames_data.get("frames", [])
    segments = audio_data.get("segments", [])

    if not segments:
        raise VideoEditError("没有音频片段数据")

    if not frames:
        raise VideoEditError("没有 PPT 帧数据")

    # 按 chapterId 排序，确保章节顺序正确
    sorted_segments = sorted(
        segments,
        key=lambda s: _parse_chapter_id(s.get("chapterId", 0))
    )

    logger.info(f"📚 加载 {len(sorted_segments)} 个章节")
    logger.info(f"📷 发现 {len(frames)} 个 PPT 帧")

    # 并发数
    max_workers = min(settings.worker_concurrency, len(sorted_segments))
    logger.info(f"⚡ 并发数: {max_workers}")

    segment_files = []
    completed = 0
    total = len(sorted_segments)

    # 使用线程池并发处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        for i, segment in enumerate(sorted_segments):
            audio_path = segment.get("audioPath")
            if not audio_path:
                logger.warning(f"   ⚠️ [{i + 1}/{total}] 章节 {segment.get('chapterId')} 无音频，跳过")
                continue

            # 根据章节获取对应的 PPT 帧
            slide_image = frames[i].get("path")
            if not slide_image:
                logger.warning(f"   ⚠️ [{i + 1}/{total}] 章节 {segment.get('chapterId')} 无图片，跳过")
                continue

            chapter_id = segment.get("chapterId")
            duration = segment.get("duration", 0)
            title = segment.get("title", "")[:30]

            logger.info(f"   📹 [{i + 1}/{total}] 章节 {chapter_id}: {title}...")

            segment_file = output_path / f"chapter_{chapter_id}.mp4"

            # 提交任务
            future = executor.submit(
                _create_slide_video,
                image_path=slide_image,
                audio_path=audio_path,
                output_path=str(segment_file),
                duration=duration,
                resolution=resolution,
                fps=fps,
            )
            futures[future] = (i, chapter_id, segment_file, duration)

        # 等待完成并更新进度
        for future in as_completed(futures):
            i, chapter_id, segment_file, duration = futures[future]
            try:
                result = future.result()
                if result:
                    segment_files.append((chapter_id, str(segment_file)))
                    completed += 1
                    logger.info(f"      ✅ [{completed}/{total}] {duration / 60:.2f} 分钟")
                else:
                    logger.warning(f"      ❌ [{i + 1}/{total}] 失败")
            except Exception as e:
                logger.error(f"   ❌ 片段 {chapter_id} 处理失败: {e}")

    # 按 chapterId 排序
    segment_files.sort(key=lambda x: _parse_chapter_id(x[0]))
    sorted_files = [f for _, f in segment_files]

    if not sorted_files:
        raise VideoEditError(f"没有成功创建任何章节视频，共 {total} 个章节")

    logger.info(f"🎬 合并 {len(sorted_files)} 个章节视频...")

    update_progress(
        task_id,
        ProgressStep.VIDEO_EDIT,
        0.9,
        f"正在合并 {len(sorted_files)} 个片段...",
    )

    # 合并视频（优先使用 stream copy）
    merged = _merge_videos_optimized(sorted_files, final_output, encoder)

    return merged


def _parse_chapter_id(chapter_id: Any) -> int:
    """
    解析章节 ID 为整数（支持字符串格式如 "chapter_1"）

    Args:
        chapter_id: 章节 ID

    Returns:
        整数 ID
    """
    if isinstance(chapter_id, int):
        return chapter_id

    # 提取数字部分
    import re
    match = re.search(r'\d+', str(chapter_id))
    if match:
        return int(match.group())

    return 0


def _get_slide_image_for_segment(
    segment: dict[str, Any],
    frames: list[dict[str, Any]],
) -> Optional[str]:
    """
    根据章节获取对应的 PPT 帧图片

    Args:
        segment: 章节片段数据
        frames: PPT 帧列表

    Returns:
        图片路径，如果找不到则返回 None
    """
    # 优先使用 segment 自带的 slideImage
    if segment.get("slideImage"):
        slide_path = segment["slideImage"]
        if Path(slide_path).exists():
            return slide_path

    # 获取章节开始时间
    start_time = segment.get("startTime", 0)

    if not frames:
        return None

    # 找到最接近章节开始时间的帧（时间戳小于等于开始时间）
    closest_frame = None
    for frame in frames:
        timestamp = frame.get("timestamp", 0)
        if timestamp <= start_time:
            closest_frame = frame
        else:
            break  # frames 已按时间排序，后面的都更大

    # 如果没找到，使用第一帧
    if closest_frame is None:
        closest_frame = frames[0]

    frame_path = closest_frame.get("path")
    if frame_path and Path(frame_path).exists():
        return frame_path

    return None


def _create_slide_video(
    image_path: str,
    audio_path: str,
    output_path: str,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 30,
) -> bool:
    """
    创建单章幻灯片视频（图片 + 音频）

    使用统一的编码参数，确保所有章节视频完全一致，以便合并时可用 stream copy。

    Args:
        image_path: 图片路径
        audio_path: 音频路径
        output_path: 输出路径
        duration: 视频时长（秒）
        resolution: 分辨率 (如 "1920x1080")
        fps: 帧率

    Returns:
        是否成功
    """
    try:
        # 转换为绝对路径
        abs_image = Path(image_path).resolve().as_posix()
        abs_audio = Path(audio_path).resolve().as_posix()
        abs_output = Path(output_path).resolve().as_posix()

        # 解析分辨率
        width, height = resolution.split('x')

        # 构建 FFmpeg 命令
        # 关键：分辨率、帧率、编码预设、音频采样率必须完全相同
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', abs_image,
            '-i', abs_audio,
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                   f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
            '-r', str(fps),                    # 固定帧率
            '-c:v', 'libx264',
            '-preset', 'fast',                 # 固定编码预设
            '-tune', 'stillimage',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ar', '44100',                    # 固定音频采样率
            '-ac', '2',                        # 固定声道数
            '-t', str(duration),
            '-shortest',
            abs_output,
        ]

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=600,
        )

        return True

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"❌ 创建幻灯片视频失败: {error_msg}")
        return False
    except Exception as e:
        logger.error(f"❌ 创建幻灯片视频失败: {e}")
        return False


def _merge_videos_optimized(
    video_files: list[str],
    output_path: str,
    encoder: EncoderConfig,
) -> str:
    """
    优化的视频合并（优先 stream copy，失败则降级到重新编码）

    Args:
        video_files: 视频文件列表
        output_path: 输出路径
        encoder: 编码器配置

    Returns:
        输出路径
    """
    if not video_files:
        raise VideoEditError("没有视频文件可合并")

    if len(video_files) == 1:
        shutil.copy2(video_files[0], output_path)
        return output_path

    # 生成 concat 文件
    concat_file = Path(output_path).parent / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for video_file in video_files:
            # 转换为绝对路径
            abs_path = Path(video_file).resolve().as_posix()
            f.write(f"file '{abs_path}'\n")

    try:
        # 策略 1: 优先使用 stream copy（速度快 10-50 倍）
        logger.info("⚡ 尝试 stream copy 模式...")
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(concat_file),
            '-c', 'copy',
            output_path,
        ]

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=600,
        )

        logger.info("✅ stream copy 成功")
        concat_file.unlink()
        return output_path

    except subprocess.CalledProcessError as e:
        # 策略 2: 降级到重新编码
        error_msg = e.stderr.decode() if e.stderr else ''
        logger.warning(f"⚠️ stream copy 失败: {error_msg}")
        logger.info("🔄 降级到重新编码模式...")

        try:
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
            ] + encoder.to_list() + [
                '-c:a', 'aac',
                '-b:a', '192k',
                output_path,
            ]

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=1800,  # 重新编码需要更长时间
            )

            logger.info("✅ 重新编码成功")
            concat_file.unlink()
            return output_path

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise VideoEditError(f"合并视频失败: {error_msg}") from e


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

    logger.info(f"🎙️ 合并视频和音频: {video_path} + {audio_path}")

    try:
        result = merge_audio_video(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_path,
        )

        return {
            "success": True,
            "output": result,
        }

    except Exception as e:
        logger.error(f"❌ 合并视频和音频失败: {e}")
        raise VideoEditError(f"合并失败: {e}") from e