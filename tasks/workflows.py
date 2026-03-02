"""
视频处理工作流编排

定义完整的视频处理流程，将各个任务串联起来。
"""

from celery import chain, chord, group, shared_task
from celery.utils.log import get_task_logger

from tasks.celery_app import celery_app
from tasks.video.download import download_video, receive_video
from tasks.video.audio_extract import extract_audio_task, upload_audio_for_asr
from tasks.video.edit import edit_video, merge_video_with_audio
from tasks.asr.transcribe import transcribe_audio, convert_transcript
from tasks.ppt.extract import extract_ppt_frames
from tasks.ppt.ocr import ocr_slides
from tasks.llm.classify import classify_content
from tasks.llm.segment import segment_chapters
from tasks.llm.summarize import summarize_content, condense_for_tts
from tasks.tts.generate import generate_tts

logger = get_task_logger(__name__)


@shared_task(name="tasks.workflows.passthrough")
def _passthrough_result(prev_result: dict, task_id: str) -> str:
    """桥接任务，用于将前一个任务的结果与 group 隔离"""
    logger.info(f"Bridge task for {task_id}, previous result: {prev_result.get('status', 'unknown')}")
    return task_id


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


def _call_task(task_func, **kwargs):
    """
    直接调用任务的原始函数，绕过 Celery 调度机制。

    避免创建嵌套的 Celery Result 对象，直接获取并调用底层函数。
    对于异步任务，使用当前事件循环执行。
    """
    import asyncio

    # 获取原始函数 (绕过 Celery 装饰器)
    if hasattr(task_func, '__wrapped__'):
        func = task_func.__wrapped__
    else:
        # 对于 shared_task，获取 run 方法
        func = getattr(task_func, 'run', task_func)

    # 调用函数
    result = func(**kwargs)

    # 处理异步结果
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(result)

    return result


@shared_task(name="tasks.workflows.process_video", bind=True)
def process_video_workflow(
    self,
    task_id: str,
    video_url: str | None = None,
    video_path: str | None = None,
    video_name: str = "video",
    mode: str = "essential",
    tts_engine: str = "dashscope",
    tts_voice: str = "Cherry",
    skip_transcribe: bool = False,
    skip_ocr: bool = False,
    options: dict | None = None,
) -> dict:
    """
    完整的视频处理工作流 (同步执行)

    直接在当前 worker 中依次执行各步骤，避免嵌套 chain dispatch 问题。

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        video_url: 视频 URL (可选)
        video_path: 本地视频路径 (可选)
        video_name: 视频名称
        mode: 浓缩模式 (essential, complete)
        tts_engine: TTS 引擎
        tts_voice: TTS 音色
        skip_transcribe: 跳过 ASR 转录
        skip_ocr: 跳过 PPT OCR
        options: 其他选项

    Returns:
        处理结果
    """
    from services.redis_client import set_task_status, update_progress
    import nest_asyncio

    # 在工作流开始时应用 nest_asyncio，以支持嵌套事件循环
    nest_asyncio.apply()

    logger.info(f"开始视频处理工作流: task_id={task_id}, mode={mode}")

    paths = get_output_paths(task_id, video_name)

    try:
        # ===== 步骤 1: 获取视频 =====
        video_file = f"{paths['base']}/input/{task_id}.mp4"

        if video_url:
            logger.info(f"下载视频: {video_url}")
            download_result = _call_task(download_video,
                task_id=task_id,
                video_url=video_url,
                output_path=video_file,
            )
            # download_video 返回实际的文件路径
            video_file = download_result.get("video_path", video_file)
            logger.info(f"视频已下载到: {video_file}")
        elif video_path:
            logger.info(f"接收本地视频: {video_path}")
            _call_task(receive_video,
                task_id=task_id,
                video_path=video_path,
                work_dir=f"{paths['base']}/input",
            )
        else:
            raise ValueError("必须提供 video_url 或 video_path")

        # ===== 步骤 2: ASR + PPT 并行执行 =====
        import concurrent.futures

        def run_asr_branch():
            """ASR 分支（同步）"""
            logger.info("🎤 开始 ASR 分支...")
            
            _call_task(extract_audio_task,
                task_id=task_id,
                video_path=video_file,
                output_dir=paths['transcript'],
            )

            upload_result = _call_task(upload_audio_for_asr,
                task_id=task_id,
                audio_path=f"{paths['transcript']}/audio.mp3",
            )

            audio_url_resolved = upload_result.get("url", "")
            _call_task(transcribe_audio,
                task_id=task_id,
                audio_url=audio_url_resolved,
                output_dir=paths['transcript'],
            )

            _call_task(convert_transcript,
                task_id=task_id,
                transcript_file=f"{paths['transcript']}/transcript.json",
                output_dir=paths['script'],
            )
            
            logger.info("✅ ASR 分支完成")
            return {"branch": "asr", "success": True}

        def run_ppt_branch():
            """PPT 分支（同步）"""
            logger.info("📷 开始 PPT 分支...")
            
            _call_task(extract_ppt_frames,
                task_id=task_id,
                video_path=video_file,
                output_dir=paths['ppt'],
                method="opencv",
            )

            _call_task(ocr_slides,
                task_id=task_id,
                frames_dir=f"{paths['ppt']}/images",
                frames_info_file=f"{paths['ppt']}/frames_info.json",
                output_dir=paths['ppt'],
                structure=True,
            )
            
            logger.info("✅ PPT 分支完成")
            return {"branch": "ppt", "success": True}

        # 使用线程池并行执行
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            if not skip_transcribe:
                futures.append(executor.submit(run_asr_branch))
            
            if not skip_ocr:
                futures.append(executor.submit(run_ppt_branch))
            
            # 等待所有分支完成
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    logger.info(f"分支完成: {result}")
                except Exception as e:
                    logger.error(f"分支执行失败: {e}", exc_info=True)
                    raise

        logger.info("✅ ASR 和 PPT 分支全部完成")

        # ===== 步骤 3: LLM 分类 =====
        logger.info("开始内容分类...")
        _call_task(classify_content,
            task_id=task_id,
            sentences_file=f"{paths['script']}/sentences.txt",
            ocr_result_file=f"{paths['ppt']}/ocr_result.json",
            output_dir=paths['script'],
        )

        # ===== 步骤 4: 章节切分 =====
        logger.info("开始章节切分...")
        _call_task(segment_chapters,
            task_id=task_id,
            classification_file=f"{paths['script']}/classification.json",
            ocr_result_file=f"{paths['ppt']}/ocr_result.json",
            sentences_file=f"{paths['script']}/sentences.txt",
            output_dir=paths['script'],
        )

        # ===== 步骤 5: 内容总结 =====
        logger.info("开始内容总结...")
        _call_task(summarize_content,
            task_id=task_id,
            classification_file=f"{paths['script']}/classification.json",
            outline_file=f"{paths['script']}/outline.json",
            output_dir=paths['script'],
            mode=mode,
        )

        # ===== 步骤 6: TTS 文本浓缩 =====
        logger.info("开始 TTS 文本浓缩...")
        _call_task(condense_for_tts,
            task_id=task_id,
            classification_file=f"{paths['script']}/classification.json",
            output_dir=paths['script'],
            mode=mode,
        )

        # ===== 步骤 7: TTS 生成 =====
        logger.info("开始 TTS 生成...")
        _call_task(generate_tts,
            task_id=task_id,
            condensed_file=f"{paths['script']}/condensed.json",
            output_dir=paths['audio'],
            engine=tts_engine,
            voice=tts_voice,
        )

        # ===== 步骤 8: 合成视频和音频 =====
        logger.info("开始合成视频和音频...")
        _call_task(edit_video,
            task_id=task_id,
            video_path=video_file,
            frames_info_file=f"{paths['ppt']}/frames_info.json",
            audio_timing_file=f"{paths['audio']}/audio_timing.json",
            output_dir=paths['video'],
            mode=mode,
        )

        # ===== 步骤 10: 汇总结果 =====
        logger.info("汇总处理结果...")
        result = _call_task(finalize_processing,
            prev_result={},
            task_id=task_id,
            paths=paths,
        )

        return result

    except Exception as e:
        logger.error(f"视频处理工作流失败: {e}", exc_info=True)
        set_task_status(
            task_id,
            "failed",
            current_step="error",
            message=f"处理失败: {str(e)}",
        )
        raise


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
    # 使用 si() 创建不可变签名，防止接收前一个任务的结果
    asr_branch = _build_asr_branch(task_id, paths, immutable=True)
    ppt_branch = _build_ppt_branch(task_id, paths, immutable=True)

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

    # 视频剪辑步骤 (可选)
    edit_video_step = edit_video.s(
        task_id=task_id,
        video_path=f"{paths['base']}/input/{task_id}.mp4",
        classification_file=f"{paths['script']}/classification.json",
        output_dir=paths['video'],
        mode=mode,
    )

    # 合成视频和 TTS 音频步骤 (可选)
    merge_video_step = merge_video_with_audio.s(
        task_id=task_id,
        video_path=None,  # 从上一步获取
        audio_path=f"{paths['audio']}/tts_audio.mp3",
        output_path=f"{paths['video']}/condensed_tts.mp4",
    )

    # 最终汇总任务
    final_step = finalize_processing.s(
        task_id=task_id,
        paths=paths,
    )

    # 构建任务链: prev -> bridge -> [asr, ppt] -> classify -> segment -> summarize -> [condense, tts] -> [edit, merge] -> finalize
    # 使用 group 并让所有任务都是不可变的，防止接收前一个任务的结果
    return chain(
        prev_step,
        group(asr_branch, ppt_branch),
        classify_step,
        segment_step,
        summarize_step,
        chain(condense_tts_step, tts_step),
        chain(edit_video_step, merge_video_step),
        final_step,
    )


def _build_asr_branch(task_id: str, paths: dict, immutable: bool = False) -> chain:
    """构建 ASR 分支"""
    # 使用 .si() 代替 .s() 当 immutable=True 时
    sig = extract_audio_task.si if immutable else extract_audio_task.s
    extract_step = sig(
        task_id=task_id,
        video_path=f"{paths['base']}/input/{task_id}.mp4",
        output_dir=paths['transcript'],
    )

    sig = upload_audio_for_asr.si if immutable else upload_audio_for_asr.s
    upload_step = sig(
        task_id=task_id,
        audio_path=f"{paths['transcript']}/audio.mp3",
    )

    sig = transcribe_audio.si if immutable else transcribe_audio.s
    transcribe_step = sig(
        task_id=task_id,
        audio_url=None,  # 从上一步获取
        output_dir=paths['transcript'],
    )

    sig = convert_transcript.si if immutable else convert_transcript.s
    convert_step = sig(
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


def _build_ppt_branch(task_id: str, paths: dict, immutable: bool = False) -> chain:
    """构建 PPT 分支"""
    # 使用 .si() 代替 .s() 当 immutable=True 时
    sig = extract_ppt_frames.si if immutable else extract_ppt_frames.s
    extract_step = sig(
        task_id=task_id,
        video_path=f"{paths['base']}/input/{task_id}.mp4",
        output_dir=paths['ppt'],
        method="opencv",
    )

    sig = ocr_slides.si if immutable else ocr_slides.s
    ocr_step = sig(
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
        # 转录
        "transcript": f"{paths['transcript']}/transcript.json",

        # 文稿
        "classification": f"{paths['script']}/classification.json",
        "classification_md": f"{paths['script']}/classification.md",
        "condensed": f"{paths['script']}/condensed.json",
        "key_points": f"{paths['script']}/key_points.md",
        "outline": f"{paths['script']}/outline.json",
        "outline_md": f"{paths['script']}/outline.md",
        "segments": f"{paths['script']}/segments.json",
        "sentences": f"{paths['script']}/sentences.txt",
        "subtitles_words": f"{paths['script']}/subtitles_words.json",
        "summary": f"{paths['script']}/summary.md",
        
        # 音频
        "tts_audio": f"{paths['audio']}/tts_audio.mp3",

        # 视频
        "condensed_video": f"{paths['video']}/condensed_course.mp4",

        # PPT
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
