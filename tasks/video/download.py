"""
视频下载/接收任务

处理视频文件的下载或接收，并存储到指定位置。
"""

import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.storage import get_storage
from services.redis_client import update_progress

logger = setup_logging()


class VideoDownloadError(VideoProcessingException):
    """视频下载错误"""
    pass


@shared_task(
    name="tasks.video.download",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def download_video(
    self,
    task_id: str,
    video_url: str,
    output_path: str,
) -> dict[str, Any]:
    """
    下载视频文件

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_url: 视频 URL
        output_path: 输出路径

    Returns:
        下载结果信息

    Raises:
        VideoDownloadError: 下载失败
    """
    logger.info(f"开始下载视频: {video_url}")
    update_progress(
        task_id,
        "video_download",
        0.0,
        f"正在下载视频: {video_url}",
    )

    try:
        # 确保输出目录存在
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 检查是否为本地文件 (file:// URL)
        if video_url.startswith("file://"):
            # 移除 file:// 前缀并解码 URL 编码
            local_path = unquote(video_url[7:])  # 移除 "file://"
            logger.info(f"检测到本地文件 URL，解析后: {local_path}")

            # 修复 Windows 路径格式: /c:/path -> c:/path 或 c:\path
            if local_path.startswith("/") and len(local_path) > 2 and local_path[2] == ":":
                # Windows 路径: /C:/... -> C:/...
                local_path = local_path[1:]

            # 尝试多种路径格式
            path_obj = Path(local_path)
            if not path_obj.exists():
                # 尝试使用原始路径（保留斜杠）
                import os
                if os.path.exists(local_path):
                    path_obj = Path(local_path)
                else:
                    raise VideoDownloadError(f"本地文件不存在: {local_path}")

            logger.info(f"检测到本地文件，复制: {path_obj} -> {output_file}")

            # 复制文件
            shutil.copy2(str(path_obj), output_file)
            file_size = output_file.stat().st_size

            logger.info(f"视频复制完成: {output_file} ({file_size} bytes)")
        else:
            # 下载远程文件
            response = requests.get(video_url, stream=True, timeout=300)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(output_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # 更新进度
                        if total_size > 0:
                            progress = min(0.1, downloaded / total_size * 0.1)
                            update_progress(
                                task_id,
                                "video_download",
                                progress,
                                f"正在下载视频: {downloaded / 1024 / 1024:.1f}MB / {total_size / 1024 / 1024:.1f}MB",
                            )

            file_size = output_file.stat().st_size
            logger.info(f"视频下载完成: {output_file} ({file_size} bytes)")

        update_progress(
            task_id,
            "video_download",
            0.1,
            f"视频处理完成: {output_file.name}",
        )

        return {
            "success": True,
            "video_path": str(output_file),
            "file_size": file_size,
            "filename": output_file.name,
        }

    except requests.RequestException as e:
        logger.error(f"下载视频失败: {e}")
        update_progress(
            task_id,
            "video_download",
            0.0,
            f"下载失败: {str(e)}",
        )
        raise VideoDownloadError(f"下载视频失败: {e}")
    except Exception as e:
        logger.error(f"处理视频下载时发生错误: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task(
    name="tasks.video.receive",
    bind=True,
)
def receive_video(
    self,
    task_id: str,
    video_path: str,
    work_dir: str,
) -> dict[str, Any]:
    """
    接收已上传的视频文件

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 本地视频文件路径
        work_dir: 工作目录

    Returns:
        视频信息
    """
    logger.info(f"接收视频文件: {video_path}")
    update_progress(
        task_id,
        "video_receive",
        0.05,
        f"接收视频: {Path(video_path).name}",
    )

    try:
        video_file = Path(video_path)

        if not video_file.exists():
            raise VideoDownloadError(f"视频文件不存在: {video_path}")

        file_size = video_file.stat().st_size

        # 创建工作目录
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)

        # 重命名为 task_id.mp4，与后续任务路径匹配
        final_path = work_path / f"{task_id}.mp4"

        # 如果视频文件不在工作目录，复制过去
        if video_file.parent != work_path:
            shutil.copy2(video_file, final_path)
            logger.info(f"视频文件已复制到: {final_path}")

        update_progress(
            task_id,
            "video_receive",
            0.1,
            f"视频接收完成: {video_file.name}",
        )

        return {
            "success": True,
            "video_path": str(final_path),
            "file_size": file_size,
            "filename": final_path.name,
            "work_dir": str(work_path),
        }

    except Exception as e:
        logger.error(f"接收视频文件时发生错误: {e}")
        raise VideoDownloadError(f"接收视频失败: {e}")


@shared_task(
    name="tasks.video.upload_to_storage",
    bind=True,
)
def upload_video_to_storage(
    self,
    task_id: str,
    video_path: str,
    object_name: str | None = None,
) -> dict[str, Any]:
    """
    上传视频到对象存储

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 本地视频路径
        object_name: 对象名称 (可选)

    Returns:
        上传结果
    """
    logger.info(f"上传视频到存储: {video_path}")

    try:
        storage = get_storage()
        video_file = Path(video_path)

        if not video_file.exists():
            raise VideoDownloadError(f"视频文件不存在: {video_path}")

        if object_name is None:
            object_name = f"videos/{video_file.name}"

        # 上传文件
        url = storage.upload(str(video_file), object_name)

        logger.info(f"视频上传成功: {url}")

        return {
            "success": True,
            "url": url,
            "object_name": object_name,
        }

    except Exception as e:
        logger.error(f"上传视频到存储时发生错误: {e}")
        raise VideoDownloadError(f"上传视频失败: {e}")
