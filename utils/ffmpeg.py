"""
FFmpeg 封装模块

提供 FFmpeg 命令的同步封装，支持：
- 音频提取
- 帧提取
- 视频剪辑与合成
- 音视频合成
- 视频信息获取
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from core.exceptions import VideoProcessingException


class FFmpegError(VideoProcessingException):
    """FFmpeg 执行错误"""
    pass


def run_ffmpeg(
    args: list[str],
    timeout: int = 3600,
    check: bool = True,
    use_ffprobe: bool = False,
) -> tuple[int, str, str]:
    """
    执行 FFmpeg/FFprobe 命令

    Args:
        args: FFmpeg 命令参数列表
        timeout: 超时时间 (秒)
        check: 是否检查退出码
        use_ffprobe: 是否使用 ffprobe 而不是 ffmpeg

    Returns:
        (exit_code, stdout, stderr)

    Raises:
        FFmpegError: FFmpeg 执行失败
    """
    from core.logging import setup_logging
    logger = setup_logging()

    cmd = ["ffprobe" if use_ffprobe else "ffmpeg"] + args
    logger.info(f"Running {'ffprobe' if use_ffprobe else 'ffmpeg'} with args: {args[:3]}... (total {len(args)} args)")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )

        logger.info(f"{'FFprobe' if use_ffprobe else 'FFmpeg'} exited with code {result.returncode}")

        # 安全地解码 stdout 和 stderr (处理 None 情况)
        stdout = result.stdout.decode("utf-8", errors="ignore") if result.stdout is not None else ""
        stderr = result.stderr.decode("utf-8", errors="ignore") if result.stderr is not None else ""

        if check and result.returncode != 0:
            raise FFmpegError(
                f"{'FFprobe' if use_ffprobe else 'FFmpeg'} failed with code {result.returncode}: {stderr}"
            )

        return result.returncode, stdout, stderr

    except subprocess.TimeoutExpired:
        raise FFmpegError(f"FFmpeg timeout after {timeout} seconds")
    except FileNotFoundError:
        exe_name = "ffprobe" if use_ffprobe else "ffmpeg"
        raise FFmpegError(f"{exe_name} not found. Please ensure FFmpeg is installed and in PATH.")
    except Exception as e:
        logger.error(f"Exception in run_ffmpeg: {type(e).__name__}: {e}")
        raise FFmpegError(f"Unexpected error running {'ffprobe' if use_ffprobe else 'ffmpeg'}: {e}")


def extract_audio(
    video_path: str,
    output_path: str,
    codec: str = "libmp3lame",
    bitrate: str | None = None,
) -> str:
    """
    提取音频

    Args:
        video_path: 视频文件路径
        output_path: 输出音频路径
        codec: 音频编码 (默认 libmp3lame)
        bitrate: 比特率 (可选)

    Returns:
        输出文件路径

    Raises:
        FFmpegError: 提取失败
    """
    args = [
        "-i", video_path,
        "-vn",  # 不要视频
        "-acodec", codec,
    ]

    if bitrate:
        args.extend(["-b:a", bitrate])

    args.extend(["-y", output_path])

    run_ffmpeg(args)
    return output_path


def extract_frames(
    video_path: str,
    output_dir: str,
    pattern: str = "frame_%05d.jpg",
    fps: float | None = None,
    quality: int = 2,
) -> list[str]:
    """
    提取关键帧 [V2 - FIXED] (基于固定帧率或场景变化)

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        pattern: 文件名模式
        fps: 帧率 (可选，如果指定则使用固定间隔采样，否则使用场景检测)
        quality: JPEG 质量 (1-31)

    Returns:
        提取的帧文件路径列表 (字符串列表)

    Raises:
        FFmpegError: 提取失败
    """
    from core.logging import setup_logging
    logger = setup_logging()

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_pattern = str(Path(output_dir) / pattern)

    args = ["-i", video_path]

    # 如果指定了 fps，使用固定帧率采样
    if fps is not None:
        # 确保 fps 是数值类型
        try:
            fps_value = float(fps)
        except (ValueError, TypeError):
            logger.warning(f"无效的 fps 值: {fps}, 使用默认值 0.2")
            fps_value = 0.2

        args.extend([
            "-vf", f"fps={fps_value}",
            "-qscale:v", str(quality),
        ])
    else:
        # 使用场景检测
        args.extend([
            "-vf", "select='gt(scene,0.3)'",  # 场景变化阈值
            "-vsync", "vfr",  # 可变帧率
            "-qscale:v", str(quality),
        ])

    args.extend(["-y", output_pattern])

    logger.info(f"Extracting frames with fps={fps}, pattern={pattern}")
    run_ffmpeg(args)

    # 返回提取的文件列表 (转换为字符串列表)
    frame_files = sorted(Path(output_dir).glob(pattern.replace("%05d", "*")))
    result = [str(f) for f in frame_files]

    logger.info(f"Extracted {len(result)} frames")
    return result


def concat_videos(
    video_list: list[str],
    output_path: str,
    method: str = "concat",
) -> str:
    """
    合并视频

    Args:
        video_list: 视频文件路径列表
        output_path: 输出文件路径
        method: 合并方法 ("concat", "filter")

    Returns:
        输出文件路径

    Raises:
        FFmpegError: 合并失败
    """
    if method == "concat":
        # 使用 concat 协议
        # 创建临时文件列表
        list_file = Path(output_path).with_suffix(".txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for video in video_list:
                video_path = Path(video).resolve()
                # 在 Windows 上需要转义反斜杠
                video_str = str(video_path).replace("\\", "/")
                f.write(f"file '{video_str}'\n")

        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-y", output_path,
        ]

        try:
            run_ffmpeg(args)
        finally:
            list_file.unlink(missing_ok=True)

    else:
        # 使用 filter 方法 (重新编码)
        inputs = []
        filter_complex = ""
        for i, video in enumerate(video_list):
            inputs.extend(["-i", video])
            filter_complex += f"[{i}:v]"

        filter_complex += f"concat=n={len(video_list)}:v=1[out]"

        args = inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-y", output_path,
        ]

        run_ffmpeg(args)

    return output_path


def merge_audio_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    audio_codec: str = "aac",
) -> str:
    """
    合并音视频

    Args:
        video_path: 视频文件路径
        audio_path: 音频文件路径
        output_path: 输出文件路径
        audio_codec: 音频编码

    Returns:
        输出文件路径

    Raises:
        FFmpegError: 合并失败
    """
    args = [
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",  # 复制视频流
        "-c:a", audio_codec,
        "-shortest",  # 以最短的流为准
        "-y", output_path,
    ]

    run_ffmpeg(args)
    return output_path


def cut_video(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    copy: bool = True,
) -> str:
    """
    剪裁视频

    Args:
        video_path: 视频文件路径
        output_path: 输出文件路径
        start_time: 开始时间 (秒)
        end_time: 结束时间 (秒)
        copy: 是否复制流 (不重新编码)

    Returns:
        输出文件路径

    Raises:
        FFmpegError: 剪裁失败
    """
    args = [
        "-i", video_path,
        "-ss", str(start_time),
        "-to", str(end_time),
    ]

    if copy:
        args.extend(["-c", "copy"])
    else:
        args.extend(["-c:v", "libx264", "-preset", "fast"])

    args.extend(["-y", output_path])

    run_ffmpeg(args)
    return output_path


def get_video_info(video_path: str) -> dict[str, Any]:
    """
    获取视频信息

    Args:
        video_path: 视频文件路径

    Returns:
        视频信息字典，所有数值字段都是正确的类型 (int/float)

    Raises:
        FFmpegError: 获取信息失败
    """
    from core.logging import setup_logging
    logger = setup_logging()

    logger.info(f"Getting video info for: {video_path}")

    # 使用 ffprobe 获取视频信息
    args = [
        "-v", "error",
        "-select_streams", "v:0",  # 选择第一个视频流
        "-show_entries",
        "stream=width,height,duration,r_frame_rate,codec_name,nb_frames",
        "-show_entries",
        "format=duration",
        "-of", "json",
        video_path,
    ]

    exit_code, stdout, stderr = run_ffmpeg(args, check=False, use_ffprobe=True)

    # 检查 ffprobe 是否成功
    if exit_code != 0:
        raise FFmpegError(f"ffprobe failed (exit code {exit_code}): {stderr}")

    # 检查输出是否为空
    if not stdout or not stdout.strip():
        raise FFmpegError(f"ffprobe returned empty output: {stderr}")

    try:
        info = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise FFmpegError(f"Failed to parse video info JSON: {e}\nstdout: {stdout}\nstderr: {stderr}")

    # 解析信息
    stream = info.get("streams", [{}])[0]
    format_info = info.get("format", {})

    # 安全地解析 duration
    duration = 0.0
    duration_str = format_info.get("duration") or stream.get("duration") or "0"
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        logger.warning(f"无法解析 duration: {duration_str}, 使用默认值 0.0")

    # 安全地解析帧率
    r_frame_rate = stream.get("r_frame_rate", "25/1")
    fps = 25.0  # 默认值
    try:
        if isinstance(r_frame_rate, str) and "/" in r_frame_rate:
            parts = r_frame_rate.split("/")
            if len(parts) == 2:
                numerator = float(parts[0])
                denominator = float(parts[1])
                fps = numerator / denominator if denominator > 0 else 25.0
        else:
            fps = float(r_frame_rate)
    except (ValueError, TypeError, ZeroDivisionError) as e:
        logger.warning(f"无法解析帧率 '{r_frame_rate}': {e}, 使用默认值 25.0")

    # 安全地解析宽高
    try:
        width = int(stream.get("width", 1920))
    except (ValueError, TypeError):
        width = 1920

    try:
        height = int(stream.get("height", 1080))
    except (ValueError, TypeError):
        height = 1080

    return {
        "width": width,
        "height": height,
        "duration": duration,  # 确保是 float
        "fps": fps,  # 确保是 float
        "codec": stream.get("codec_name", "unknown"),
        "path": video_path,
    }


def resize_video(
    video_path: str,
    output_path: str,
    width: int | None = None,
    height: int | None = None,
    scale: str | None = None,
) -> str:
    """
    调整视频尺寸

    Args:
        video_path: 视频文件路径
        output_path: 输出文件路径
        width: 目标宽度
        height: 目标高度
        scale: 缩放比例 (如 "iw/2:ih/2")

    Returns:
        output_path

    Raises:
        FFmpegError: 调整失败
    """
    vf_filter = ""
    if width or height:
        vf_filter = f"scale={width or -1}:{height or -1}"
    elif scale:
        vf_filter = f"scale={scale}"

    args = [
        "-i", video_path,
        "-vf", vf_filter,
        "-c:a", "copy",
        "-y", output_path,
    ]

    run_ffmpeg(args)
    return output_path


def convert_format(
    input_path: str,
    output_path: str,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
) -> str:
    """
    转换视频格式

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        video_codec: 视频编码
        audio_codec: 音频编码

    Returns:
        output_path

    Raises:
        FFmpegError: 转换失败
    """
    args = [
        "-i", input_path,
        "-c:v", video_codec,
        "-preset", "fast",
        "-c:a", audio_codec,
        "-y", output_path,
    ]

    run_ffmpeg(args)
    return output_path


def check_ffmpeg_installed() -> bool:
    """
    检查 FFmpeg 是否已安装

    Returns:
        FFmpeg 是否可用
    """
    try:
        import shutil
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


def get_ffmpeg_version() -> str | None:
    """
    获取 FFmpeg 版本

    Returns:
        FFmpeg 版本字符串，如果未安装返回 None
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # 解析版本信息
            for line in result.stdout.split('\n'):
                if 'ffmpeg version' in line:
                    return line.strip()
        return result.stdout.split('\n')[0] if result.stdout else None
    except Exception:
        return None
