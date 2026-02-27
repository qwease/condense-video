"""
FFmpeg 封装模块

提供 FFmpeg 命令的异步封装，支持：
- 音频提取
- 帧提取
- 视频剪辑与合成
- 音视频合成
- 视频信息获取
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from core.exceptions import VideoProcessingException


class FFmpegError(VideoProcessingException):
    """FFmpeg 执行错误"""
    pass


async def run_ffmpeg(
    args: list[str],
    timeout: int = 3600,
    check: bool = True,
) -> tuple[int, str, str]:
    """
    执行 FFmpeg 命令

    Args:
        args: FFmpeg 命令参数列表
        timeout: 超时时间 (秒)
        check: 是否检查退出码

    Returns:
        (exit_code, stdout, stderr)

    Raises:
        FFmpegError: FFmpeg 执行失败
    """
    cmd = ["ffmpeg"] + args

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        if check and process.returncode != 0:
            raise FFmpegError(
                f"FFmpeg failed with code {process.returncode}: {stderr.decode()}"
            )

        return process.returncode, stdout.decode(), stderr.decode()

    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise FFmpegError(f"FFmpeg timeout after {timeout} seconds")


async def extract_audio(
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

    await run_ffmpeg(args)
    return output_path


async def extract_frames(
    video_path: str,
    output_dir: str,
    pattern: str = "frame_%05d.jpg",
    fps: float | None = None,
    quality: int = 2,
) -> list[str]:
    """
    提取关键帧 (基于场景变化)

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        pattern: 文件名模式
        fps: 帧率 (可选，默认使用原视频 fps)
        quality: JPEG 质量 (1-31)

    Returns:
        提取的帧文件路径列表

    Raises:
        FFmpegError: 提取失败
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_pattern = str(Path(output_dir) / pattern)

    args = [
        "-i", video_path,
        "-vf", "select='gt(scene,0.3)'",  # 场景变化阈值
        "-vsync", "vfr",  # 可变帧率
        "-qscale:v", str(quality),
    ]

    if fps:
        args.extend(["-r", str(fps)])

    args.extend(["-y", output_pattern])

    await run_ffmpeg(args)

    # 返回提取的文件列表
    return sorted(Path(output_dir).glob(pattern))


async def concat_videos(
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
        with open(list_file, "w") as f:
            for video in video_list:
                video_path = Path(video).resolve()
                f.write(f"file '{video_path}'\n")

        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-y", output_path,
        ]

        try:
            await run_ffmpeg(args)
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
            "-y", output_path,
        ]

        await run_ffmpeg(args)

    return output_path


async def merge_audio_video(
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

    await run_ffmpeg(args)
    return output_path


async def cut_video(
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

    await run_ffmpeg(args)
    return output_path


async def get_video_info(video_path: str) -> dict[str, Any]:
    """
    获取视频信息

    Args:
        video_path: 视频文件路径

    Returns:
        视频信息字典

    Raises:
        FFmpegError: 获取信息失败
    """
    # 使用 ffprobe 获取视频信息
    args = [
        "-v", "error",
        "-show_entries",
        "stream=0:width,height,duration,r_frame_rate,codec_name",
        "-show_entries",
        "format=duration:format",
        "-of", "json",
        video_path,
    ]

    _, stdout, _ = await run_ffmpeg(args, check=False)

    try:
        info = json.loads(stdout)
    except json.JSONDecodeError:
        raise FFmpegError(f"Failed to parse video info: {stdout}")

    # 解析信息
    stream = info.get("streams", [{}])[0]
    format_info = info.get("format", {})

    duration = float(format_info.get("duration", 0))
    if duration == 0 and stream.get("duration"):
        duration = float(stream["duration"])

    return {
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "duration": duration,
        "fps": eval(stream.get("r_frame_rate", "25")),
        "codec": stream.get("codec_name", "unknown"),
        "path": video_path,
    }


async def resize_video(
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

    await run_ffmpeg(args)
    return output_path


async def convert_format(
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

    await run_ffmpeg(args)
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
        import subprocess
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
