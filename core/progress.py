"""
进度跟踪模块

提供便捷的进度更新接口，内部使用 Redis Pub/Sub。
"""

from typing import Any

from services.redis_client import update_progress, get_progress


async def update_task_progress(
    task_id: str,
    step: str,
    progress: float,
    message: str,
    data: dict | None = None,
) -> None:
    """
    更新任务进度

    Args:
        task_id: 任务 ID
        step: 当前步骤名称
        progress: 进度 (0.0 - 1.0)
        message: 进度消息
        data: 额外的进度数据
    """
    update_progress(task_id, step, progress, message, data)


async def get_task_progress(task_id: str) -> dict[str, Any] | None:
    """
    获取任务进度

    Args:
        task_id: 任务 ID

    Returns:
        进度信息字典，如果不存在返回 None
    """
    return get_progress(task_id)


# 进度步骤定义 (与 tasks/workflows.py 配合使用)
class ProgressStep:
    """进度步骤常量"""

    VIDEO_DOWNLOAD = "video_download"
    AUDIO_EXTRACT = "audio_extract"
    PPT_EXTRACT = "ppt_extract"
    ASR_TRANSCRIBE = "asr_transcribe"
    PPT_OCR = "ppt_ocr"
    CONTENT_CLASSIFY = "content_classify"
    CHAPTER_SEGMENT = "chapter_segment"
    CONTENT_SUMMARIZE = "content_summarize"
    TTS_GENERATE = "tts_generate"
    VIDEO_EDIT = "video_edit"
    CLEANUP = "cleanup"


# 步骤权重 (用于计算总体进度)
STEP_WEIGHTS: dict[str, float] = {
    ProgressStep.VIDEO_DOWNLOAD: 0.05,
    ProgressStep.AUDIO_EXTRACT: 0.05,
    ProgressStep.PPT_EXTRACT: 0.05,
    ProgressStep.ASR_TRANSCRIBE: 0.15,
    ProgressStep.PPT_OCR: 0.15,
    ProgressStep.CONTENT_CLASSIFY: 0.10,
    ProgressStep.CHAPTER_SEGMENT: 0.05,
    ProgressStep.CONTENT_SUMMARIZE: 0.10,
    ProgressStep.TTS_GENERATE: 0.15,
    ProgressStep.VIDEO_EDIT: 0.10,
    ProgressStep.CLEANUP: 0.05,
}


def calculate_total_progress(
    completed_steps: list[str],
    current_step: str,
    step_progress: float,
) -> float:
    """
    计算总体进度

    Args:
        completed_steps: 已完成的步骤列表
        current_step: 当前步骤
        step_progress: 当前步骤的进度 (0.0 - 1.0)

    Returns:
        总体进度 (0.0 - 1.0)
    """
    # 已完成步骤的权重和
    completed_weight = sum(STEP_WEIGHTS.get(s, 0) for s in completed_steps)

    # 当前步骤的权重
    current_weight = STEP_WEIGHTS.get(current_step, 0)

    # 总进度 = 已完成 + 当前步骤进度
    return completed_weight + (current_weight * step_progress)
