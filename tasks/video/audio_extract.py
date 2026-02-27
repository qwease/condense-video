"""
音频提取任务

从视频文件中提取音频，用于 ASR 转录。
"""

from pathlib import Path
from typing import Any

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.redis_client import update_progress
from utils.ffmpeg import extract_audio

logger = setup_logging()


class AudioExtractError(VideoProcessingException):
    """音频提取错误"""
    pass


@shared_task(
    name="tasks.video.audio_extract",
    bind=True,
    max_retries=2,
)
def extract_audio_task(
    self,
    task_id: str,
    video_path: str,
    output_dir: str,
    output_filename: str = "audio.mp3",
) -> dict[str, Any]:
    """
    从视频中提取音频

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 视频文件路径
        output_dir: 输出目录
        output_filename: 输出文件名

    Returns:
        音频文件信息

    Raises:
        AudioExtractError: 提取失败
    """
    logger.info(f"开始提取音频: {video_path}")

    update_progress(
        task_id,
        ProgressStep.AUDIO_EXTRACT,
        0.1,
        "正在提取音频...",
    )

    try:
        # 确保输出目录存在
        output_path = Path(output_dir) / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 提取音频
        result_path = extract_audio(
            video_path=video_path,
            output_path=str(output_path),
            codec="libmp3lame",
            bitrate="128k",
        )

        # 等待文件写入完成
        result_file = Path(result_path)
        if not result_file.exists():
            raise AudioExtractError(f"音频文件未生成: {result_path}")

        file_size = result_file.stat().st_size

        logger.info(f"音频提取完成: {result_path} ({file_size} bytes)")

        update_progress(
            task_id,
            ProgressStep.AUDIO_EXTRACT,
            0.15,
            f"音频提取完成: {result_file.name}",
        )

        return {
            "success": True,
            "audio_path": str(result_path),
            "file_size": file_size,
            "filename": result_file.name,
            "format": "mp3",
            "codec": "libmp3lame",
        }

    except Exception as e:
        logger.error(f"提取音频时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.AUDIO_EXTRACT,
            0.0,
            f"音频提取失败: {str(e)}",
        )
        raise AudioExtractError(f"提取音频失败: {e}")


@shared_task(
    name="tasks.video.upload_audio",
    bind=True,
)
def upload_audio_for_asr(
    self,
    task_id: str,
    audio_path: str,
) -> dict[str, Any]:
    """
    上传音频文件以供 ASR 使用

    DashScope ASR 需要公网可访问的音频 URL。

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        audio_path: 音频文件路径

    Returns:
        音频 URL
    """
    logger.info(f"上传音频供 ASR 使用: {audio_path}")

    try:
        from core.storage import get_storage

        storage = get_storage()
        audio_file = Path(audio_path)

        if not audio_file.exists():
            raise AudioExtractError(f"音频文件不存在: {audio_path}")

        # 对象名称
        object_name = f"audio/{task_id}/{audio_file.name}"

        # 上传文件
        url = storage.upload(str(audio_file), object_name)

        logger.info(f"音频上传成功: {url}")

        return {
            "success": True,
            "url": url,
            "object_name": object_name,
        }

    except Exception as e:
        logger.error(f"上传音频时发生错误: {e}")
        raise AudioExtractError(f"上传音频失败: {e}")
