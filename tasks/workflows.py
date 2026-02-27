"""
视频处理工作流编排

定义完整的视频处理流程，将各个任务串联起来。
"""

from celery import chain, chord, group, shared_task
from celery.utils.log import get_task_logger

from tasks.celery_app import celery_app
from tasks.video.download import download_video, receive_video
from tasks.video.audio_extract import extract_audio_task, upload_audio_for_asr
from tasks.asr.transcribe import transcribe_audio, convert_transcript
from tasks.ppt.extract import extract_ppt_frames
from tasks.ppt.ocr import ocr_slides
from tasks.llm.classify import classify_content
from tasks.llm.segment import segment_chapters
from tasks.llm.summarize import summarize_content, condense_for_tts
from tasks.tts.generate import generate_tts

logger = get_task_logger(__name__)


# 输出目录路径配置
def get_output_paths(task_id: str, video_name: str) -> dict[str, str]:
    """获取各步骤输出路径"""
    from datetime import datetime
    from pathlib import Path

    date_str = datetime.now().strftime("%Y-%m-%d")
    base_dir = Path(f"data/output/{date_str}_{video_name}/精要提炼")

    return {
        "base": str(base_dir),
        "transcript": str(base_dir / "steps" / "1_转录"),
        "script": str(base_dir / "steps" / "2_文稿"),
        "audio": str(base_dir / "steps" / "3_音频"),
        "video": str(base_dir / "steps" / "4_视频"),
        "ppt": str(base_dir / "steps" / "5_PPT"),
    }


@shared_task(name="tasks.workflows.process_video")
def process_video_workflow(
    task_id: str,
    video_url: str | None = None,
    video_path: str | None = None,
    video_name: str = "video",
    mode: str = "essential",
    tts_engine: str = "dashscope",
    tts_voice: str = "Cherry",
) -> dict:
    """
    完整的视频处理工作流

    Args:
        task_id: 任务 ID
        video_url: 视频 URL (可选)
        video_path: 本地视频路径 (可选)
        video_name: 视频名称
        mode: 浓缩模式 (essential, complete)
        tts_engine: TTS 引擎
        tts_voice: TTS 音色

    Returns:
        处理结果
    """
    logger.info(f"开始视频处理工作流: task_id={task_id}, mode={mode}")

    paths = get_output_paths(task_id, video_name)

    # 构建任务链
    if video_url:
        # 从 URL 下载视频
        workflow = _build_download_workflow(
            task_id=task_id,
            video_url=video_url,
            paths=paths,
            mode=mode,
            tts_engine=tts_engine,
            tts_voice=tts_voice,
        )
    elif video_path:
        # 使用本地视频
        workflow = _build_local_workflow(
            task_id=task_id,
            video_path=video_path,
            paths=paths,
            mode=mode,
            tts_engine=tts_engine,
            tts_voice=tts_voice,
        )
    else:
        raise ValueError("必须提供 video_url 或 video_path")

    # 异步执行工作流
    return workflow.apply_async(task_id=task_id)


def _build_download_workflow(
    task_id: str,
    video_url: str,
    paths: dict[str, str],
    mode: str,
    tts_engine: str,
    tts_voice: str,
) -> chain:
    """构建基于下载的工作流"""
    # 步骤 1: 下载视频
    download_step = download_video.s(
        task_id=task_id,
        video_url=video_url,
        output_path=f"{paths['base']}/input/{task_id}.mp4",
    )

    # 后续步骤
    return _build_processing_chain(
        task_id=task_id,
        paths=paths,
        mode=mode,
        tts_engine=tts_engine,
        tts_voice=tts_voice,
        prev_step=download_step,
    )


def _build_local_workflow(
    task_id: str,
    video_path: str,
    paths: dict[str, str],
    mode: str,
    tts_engine: str,
    tts_voice: str,
) -> chain:
    """构建基于本地视频的工作流"""
    # 步骤 1: 接收视频
    receive_step = receive_video.s(
        task_id=task_id,
        video_path=video_path,
        work_dir=f"{paths['base']}/input",
    )

    # 后续步骤
    return _build_processing_chain(
        task_id=task_id,
        paths=paths,
        mode=mode,
        tts_engine=tts_engine,
        tts_voice=tts_voice,
        prev_step=receive_step,
    )


def _build_processing_chain(
    task_id: str,
    paths: dict,
    mode: str,
    tts_engine: str,
    tts_voice: str,
    prev_step,
) -> chain:
    """构建核心处理链"""
    # 步骤 2: 并行执行 ASR 和 PPT 提取
    asr_branch = _build_asr_branch(task_id, paths)
    ppt_branch = _build_ppt_branch(task_id, paths)

    # 并行组合
    parallel_step = group(asr_branch, ppt_branch)

    # 步骤 3: 串行处理 (需要 ASR 和 PPT 都完成)
    classify_step = classify_content.s(
        task_id=task_id,
        sentences_file=f"{paths['script']}/sentences.txt",
        ocr_result_file=f"{paths['ppt']}/ocr_result.json",
        output_dir=paths['script'],
    )

    segment_step = segment_chapters.s(
        task_id=task_id,
        classification_file=f"{paths['script']}/classification.json",
        ocr_result_file=f"{paths['ppt']}/ocr_result.json",
        sentences_file=f"{paths['script']}/sentences.txt",
        output_dir=paths['script'],
    )

    summarize_step = summarize_content.s(
        task_id=task_id,
        classification_file=f"{paths['script']}/classification.json",
        outline_file=f"{paths['script']}/outline.json",
        output_dir=paths['script'],
        mode=mode,
    )

    condense_tts_step = condense_for_tts.s(
        task_id=task_id,
        classification_file=f"{paths['script']}/classification.json",
        output_dir=paths['script'],
        mode=mode,
    )

    tts_step = generate_tts.s(
        task_id=task_id,
        condensed_file=f"{paths['script']}/condensed_for_tts.txt",
        output_dir=paths['audio'],
        engine=tts_engine,
        voice=tts_voice,
    )

    # 最终汇总任务
    final_step = finalize_processing.s(
        task_id=task_id,
        paths=paths,
    )

    # 构建任务链: prev -> [asr, ppt] -> classify -> segment -> summarize -> [condense, tts] -> finalize
    return chain(
        prev_step,
        parallel_step,
        classify_step,
        segment_step,
        summarize_step,
        chain(condense_tts_step, tts_step),
        final_step,
    )


def _build_asr_branch(task_id: str, paths: dict) -> chain:
    """构建 ASR 分支"""
    # 音频提取
    extract_step = extract_audio_task.s(
        task_id=task_id,
        video_path=f"{paths['base']}/input/{task_id}.mp4",
        output_dir=paths['transcript'],
    )

    # 上传音频
    upload_step = upload_audio_for_asr.s(
        task_id=task_id,
        audio_path=f"{paths['transcript']}/audio.mp3",
    )

    # 转录
    transcribe_step = transcribe_audio.s(
        task_id=task_id,
        audio_url=None,  # 从上一步获取
        output_dir=paths['transcript'],
    )

    # 转换格式
    convert_step = convert_transcript.s(
        task_id=task_id,
        transcript_file=f"{paths['transcript']}/transcript.json",
        output_dir=paths['script'],
    )

    return chain(
        extract_step,
        upload_step,
        transcribe_step,
        convert_step,
    )


def _build_ppt_branch(task_id: str, paths: dict) -> chain:
    """构建 PPT 分支"""
    # 提取关键帧
    extract_step = extract_ppt_frames.s(
        task_id=task_id,
        video_path=f"{paths['base']}/input/{task_id}.mp4",
        output_dir=paths['ppt'],
        method="ffmpeg",
    )

    # OCR 识别
    ocr_step = ocr_slides.s(
        task_id=task_id,
        frames_dir=f"{paths['ppt']}/images",
        frames_info_file=f"{paths['ppt']}/frames_info.json",
        output_dir=paths['ppt'],
        structure=True,
    )

    return chain(extract_step, ocr_step)


@shared_task(name="tasks.workflows.finalize")
def finalize_processing(
    prev_result,
    task_id: str,
    paths: dict,
) -> dict:
    """
    完成处理，生成最终结果

    Args:
        prev_result: 上一步骤结果
        task_id: 任务 ID
        paths: 输出路径字典

    Returns:
        最终处理结果
    """
    from pathlib import Path
    from services.redis_client import (
        save_result,
        set_task_status,
        update_progress,
    )

    logger.info(f"完成视频处理: {task_id}")

    update_progress(
        task_id,
        "finalize",
        1.0,
        "视频处理完成",
    )

    # 收集输出文件
    output_files = {
        "transcript": f"{paths['transcript']}/transcript.json",
        "classification": f"{paths['script']}/classification.json",
        "outline": f"{paths['script']}/outline.json",
        "outline_md": f"{paths['script']}/outline.md",
        "summary": f"{paths['script']}/summary.md",
        "key_points": f"{paths['script']}/key_points.md",
        "condensed": f"{paths['script']}/condensed.txt",
        "tts_audio": f"{paths['audio']}/tts_audio.mp3",
        "ppt_frames": f"{paths['ppt']}/images",
        "ppt_ocr": f"{paths['ppt']}/ocr_result.json",
    }

    # 验证文件存在
    existing_files = {}
    for key, file_path in output_files.items():
        path = Path(file_path)
        if path.exists():
            if path.is_dir():
                existing_files[key] = str(path)
            else:
                existing_files[key] = str(path)

    # 计算统计信息
    import json

    stats = {}
    if "outline" in existing_files:
        with open(existing_files["outline"], "r", encoding="utf-8") as f:
            outline_data = json.load(f)
            stats["chapter_count"] = len(outline_data.get("chapters", []))
            stats["total_duration"] = outline_data.get("total_duration", 0)

    if "classification" in existing_files:
        with open(existing_files["classification"], "r", encoding="utf-8") as f:
            class_data = json.load(f)
            stats["segment_count"] = len(class_data.get("segments", []))
            stats["statistics"] = class_data.get("statistics", {})

    result = {
        "success": True,
        "task_id": task_id,
        "files": existing_files,
        "statistics": stats,
    }

    # 保存结果到 Redis
    save_result(task_id, result)

    # 更新任务状态
    set_task_status(
        task_id,
        "success",
        progress=1.0,
        current_step="completed",
        message="视频处理完成",
        result=result,
    )

    return result


@shared_task(name="tasks.workflows.cancel")
def cancel_workflow(task_id: str) -> dict:
    """
    取消正在执行的工作流

    Args:
        task_id: 任务 ID

    Returns:
        取消结果
    """
    from celery import current_app
    from services.redis_client import set_task_status

    logger.info(f"取消工作流: {task_id}")

    # 撤销 Celery 任务
    current_app.control.revoke(task_id, terminate=True)

    # 更新状态
    set_task_status(
        task_id,
        "cancelled",
        current_step="cancelled",
        message="任务已取消",
    )

    return {
        "success": True,
        "task_id": task_id,
        "status": "cancelled",
    }


@shared_task(name="tasks.workflows.resume")
def resume_workflow(task_id: str) -> dict:
    """
    恢复中断的工作流 (断点续传)

    Args:
        task_id: 任务 ID

    Returns:
        恢复结果
    """
    from services.redis_client import get_task_status

    logger.info(f"恢复工作流: {task_id}")

    # 获取任务状态
    status = get_task_status(task_id)

    if not status:
        return {
            "success": False,
            "error": "任务不存在",
        }

    if status.get("status") == "success":
        return {
            "success": False,
            "error": "任务已完成",
        }

    # TODO: 实现断点续传逻辑
    # 需要记录每个步骤的完成状态，从失败的步骤重新开始

    return {
        "success": False,
        "error": "断点续传功能待实现",
    }
