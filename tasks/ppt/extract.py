"""
PPT 关键帧提取任务

从视频中提取 PPT 关键帧，使用场景检测或感知哈希方法。
"""

import json
from pathlib import Path
from typing import Any

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.redis_client import update_progress

logger = setup_logging()


class PPTExtractError(VideoProcessingException):
    """PPT 提取错误"""
    pass


@shared_task(
    name="tasks.ppt.extract_frames",
    bind=True,
    max_retries=2,
)
def extract_ppt_frames(
    self,
    task_id: str,
    video_path: str,
    output_dir: str,
    method: str = "ffmpeg",
) -> dict[str, Any]:
    """
    提取 PPT 关键帧

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_path: 视频文件路径
        output_dir: 输出目录
        method: 提取方法 (ffmpeg=场景检测, opencv=感知哈希)

    Returns:
        提取结果信息

    Raises:
        PPTExtractError: 提取失败
    """
    logger.info(f"开始提取 PPT 关键帧: {video_path}")

    update_progress(
        task_id,
        ProgressStep.PPT_EXTRACT,
        0.2,
        "正在提取 PPT 关键帧...",
    )

    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if method == "ffmpeg":
            # 使用 FFmpeg 场景检测
            from utils.ffmpeg import extract_frames

            images_dir = output_path / "images"
            frame_files = extract_frames(
                video_path=video_path,
                output_dir=str(images_dir),
                pattern="frame_%05d.jpg",
                fps=None,  # 使用场景检测
                quality=2,
            )

        elif method == "opencv":
            # 使用 OpenCV 感知哈希 (更精确但较慢)
            frame_files = _extract_with_opencv(
                video_path=video_path,
                output_dir=output_dir,
                task_id=task_id,
            )
        else:
            raise PPTExtractError(f"不支持的提取方法: {method}")

        # 获取视频信息
        from utils.ffmpeg import get_video_info

        video_info = get_video_info(video_path)

        # 生成帧信息 JSON
        frames_info = []
        for idx, frame_file in enumerate(frame_files):
            frame_file = Path(frame_file)
            # 从文件名提取时间戳（如果文件名包含时间信息）
            timestamp = _estimate_timestamp(idx, len(frame_files), video_info["duration"])

            frames_info.append({
                "index": idx,
                "filename": frame_file.name,
                "path": str(frame_file),
                "timestamp": round(timestamp, 3),
            })

        # 保存 frames_info.json
        info_file = output_path / "frames_info.json"
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump({
                "video_info": video_info,
                "frames": frames_info,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"PPT 关键帧提取完成: {len(frame_files)} 帧")

        update_progress(
            task_id,
            ProgressStep.PPT_EXTRACT,
            0.3,
            f"PPT 关键帧提取完成: {len(frame_files)} 帧",
        )

        return {
            "success": True,
            "frames_dir": str(output_path / "images"),
            "info_file": str(info_file),
            "frame_count": len(frame_files),
            "method": method,
        }

    except Exception as e:
        logger.error(f"提取 PPT 关键帧时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.PPT_EXTRACT,
            0.0,
            f"PPT 提取失败: {str(e)}",
        )
        raise PPTExtractError(f"提取 PPT 关键帧失败: {e}")


def _extract_with_opencv(
    video_path: str,
    output_dir: Path,
    task_id: str,
) -> list[str]:
    """
    使用 OpenCV 和感知哈希提取关键帧

    这是一个同步函数，因为 Python multiprocessing 在 Celery 中
    可能有兼容性问题。使用简化版本。
    """
    import cv2
    from PIL import Image
    import imagehash

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise PPTExtractError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 采样间隔 (每 3 秒)
    sample_interval = int(fps * 3)

    frame_files = []
    frame_idx = 0
    saved_idx = 0
    last_hash = None
    threshold = 20  # 感知哈希差异阈值

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            # 检查内容有效性
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            non_black = cv2.countNonZero(gray)
            total = gray.shape[0] * gray.shape[1]

            if non_black / total >= 0.15:  # 至少 15% 内容
                # 计算感知哈希
                pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                current_hash = imagehash.phash(pil_image, hash_size=16)

                # 检查重复
                is_duplicate = False
                if last_hash is not None:
                    diff = current_hash - last_hash
                    if diff <= threshold:
                        is_duplicate = True

                if not is_duplicate:
                    # 保存帧
                    filename = f"frame_{saved_idx:05d}.jpg"
                    filepath = images_dir / filename
                    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

                    frame_files.append(str(filepath))
                    saved_idx += 1
                    last_hash = current_hash

                    # 更新进度
                    progress = 0.2 + (frame_idx / total_frames) * 0.1
                    update_progress(
                        task_id,
                        ProgressStep.PPT_EXTRACT,
                        progress,
                        f"正在提取关键帧: {saved_idx} 帧",
                    )

        frame_idx += 1

    cap.release()
    return frame_files


def _estimate_timestamp(
    frame_idx: int,
    total_frames: int,
    video_duration: float,
) -> float:
    """估算帧的时间戳"""
    if total_frames <= 1:
        return 0.0
    return (frame_idx / (total_frames - 1)) * video_duration
