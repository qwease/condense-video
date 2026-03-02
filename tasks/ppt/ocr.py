"""
PPT OCR 识别任务

使用 DashScope VL 模型对 PPT 关键帧进行 OCR 识别。
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
from services.dashscope import DashScopeClient
from services.redis_client import update_progress

logger = setup_logging()


class PPTOCRError(VideoProcessingException):
    """PPT OCR 错误"""
    pass


@shared_task(
    name="tasks.ppt.ocr",
    bind=True,
    max_retries=2,
)
def ocr_slides(
    self,
    task_id: str,
    frames_dir: str,
    frames_info_file: str,
    output_dir: str,
    structure: bool = True,
    concurrency: int = 5,
    resume: bool = True,
) -> dict[str, Any]:
    """
    对 PPT 关键帧进行 OCR 识别

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        frames_dir: 帧图像目录
        frames_info_file: 帧信息文件
        output_dir: 输出目录
        structure: 是否提取结构化信息
        concurrency: 并发数
        resume: 是否支持断点续传

    Returns:
        OCR 结果信息

    Raises:
        PPTOCRError: OCR 失败
    """
    logger.info(f"开始 PPT OCR 识别: {frames_dir}")
    logger.info(f"配置: 并发={concurrency}, 断点续传={resume}")

    update_progress(
        task_id,
        ProgressStep.PPT_OCR,
        0.3,
        "正在进行 PPT OCR 识别...",
    )

    try:
        # 读取帧信息
        with open(frames_info_file, "r", encoding="utf-8") as f:
            frames_data = json.load(f)

        frames = frames_data.get("frames", [])
        video_info = frames_data.get("video_info", {})

        if not frames:
            raise PPTOCRError("没有找到可识别的帧")

        logger.info(f"共 {len(frames)} 帧待处理")

        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 检查断点续传
        ocr_result_file = output_path / "ocr_result.json"
        results = {"slides": [], "errors": []}

        if resume and ocr_result_file.exists():
            with open(ocr_result_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            logger.info(f"已加载 {len(results['slides'])} 个已完成的结果")

        # 过滤已处理的帧
        processed_paths = {s["framePath"] for s in results["slides"]}
        
        # 构建待处理的帧列表
        frames_path = Path(frames_dir)
        pending_frames = []

        for frame in frames:
            image_path = frames_path / frame["filename"]
            if not image_path.exists():
                logger.warning(f"⚠️ 图像文件不存在: {image_path}")
                continue
            
            if str(image_path) not in processed_paths:
                pending_frames.append({
                    "path": str(image_path),
                    "index": frame["index"],
                    "filename": frame["filename"],
                    "timestamp": frame.get("timestamp", 0),
                })

        logger.info(f"待处理: {len(pending_frames)} 帧")

        if len(pending_frames) == 0:
            logger.info("所有帧已处理完成")
            # 返回已有结果
            return _finalize_ocr_results(
                results=results,
                video_info=video_info,
                output_file=ocr_result_file,
                task_id=task_id,
            )

        # 批量 OCR
        client = DashScopeClient(api_key=settings.dashscope_api_key)

        # 获取或创建事件循环
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            # 批量处理，支持进度更新
            completed = 0
            batch_size = 20  # 每20个保存一次

            for i in range(0, len(pending_frames), batch_size):
                batch = pending_frames[i:i + batch_size]
                
                logger.info(f"处理批次 {i//batch_size + 1}/{(len(pending_frames)-1)//batch_size + 1}")

                # 批量 OCR
                ocr_results = loop.run_until_complete(
                    client.ocr_batch(
                        image_paths=[f["path"] for f in batch],
                        concurrency=concurrency,
                    )
                )

                # 处理结果
                for frame_info, ocr_result in zip(batch, ocr_results):
                    if "error" in ocr_result:
                        results["errors"].append({
                            "frame": frame_info,
                            "error": ocr_result["error"],
                        })
                        logger.warning(f"   OCR 失败: {frame_info['filename']} - {ocr_result['error']}")
                        continue

                    # 构建幻灯片数据
                    slide_data = {
                        "frameId": frame_info["index"],
                        "filename": frame_info["filename"],
                        "path": frame_info["path"],
                        "framePath": frame_info["path"],  # 兼容 JS 版本
                        "timestamp": frame_info["timestamp"],
                        "ocrText": ocr_result.get("rawText", ""),
                        "structure": {
                            "title": ocr_result.get("title", ""),
                            "subtitles": ocr_result.get("subtitles", []),
                            "body": ocr_result.get("body", []),
                            "formulas": ocr_result.get("formulas", []),
                            "keyTerms": ocr_result.get("keyTerms", []),
                            "confidence": 0.5 if ocr_result.get("parseError") else 0.9,
                        },
                    }

                    results["slides"].append(slide_data)
                    completed += 1

                    # 显示进度
                    progress = 0.3 + (completed / len(pending_frames)) * 0.15
                    logger.info(f"   进度: {completed}/{len(pending_frames)} ({completed/len(pending_frames)*100:.1f}%)")
                    
                    update_progress(
                        task_id,
                        ProgressStep.PPT_OCR,
                        progress,
                        f"正在识别 PPT: {completed}/{len(pending_frames)}",
                    )

                # 批量保存（断点续传支持）
                _save_intermediate_results(results, ocr_result_file)

        finally:
            # 不关闭循环，可能被其他任务使用
            pass

        # 最终保存
        return _finalize_ocr_results(
            results=results,
            video_info=video_info,
            output_file=ocr_result_file,
            task_id=task_id,
        )

    except Exception as e:
        logger.error(f"PPT OCR 识别时发生错误: {e}", exc_info=True)
        update_progress(
            task_id,
            ProgressStep.PPT_OCR,
            0.0,
            f"PPT OCR 失败: {str(e)}",
        )
        raise PPTOCRError(f"PPT OCR 识别失败: {e}")


def _save_intermediate_results(results: dict, output_file: Path):
    """保存中间结果（支持断点续传）"""
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存中间结果失败: {e}")


def _finalize_ocr_results(
    results: dict,
    video_info: dict,
    output_file: Path,
    task_id: str,
) -> dict[str, Any]:
    """
    最终化 OCR 结果，生成统一输出格式
    
    参考 JS 版本的 unifiedOutput 结构
    """
    # 按 frameId 排序
    results["slides"].sort(key=lambda s: s.get("frameId", 0))

    # 统一输出格式（兼容 JS 版本）
    unified_output = {
        "videoInfo": video_info,
        "totalSlides": len(results.get("slides", [])),
        "successCount": len(results.get("slides", [])),
        "slides": results.get("slides", []),
    }

    # 只在有错误时包含 errors 字段
    if results.get("errors"):
        unified_output["errorCount"] = len(results.get("errors", []))
        unified_output["errors"] = results.get("errors", [])
    else:
        unified_output["errorCount"] = 0

    # 保存统一输出文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(unified_output, f, ensure_ascii=False, indent=2)

    logger.info(f"\nOCR 完成！")
    logger.info(f"   成功: {len(results.get('slides', []))} 帧")
    logger.info(f"   失败: {len(results.get('errors', []))} 帧")
    logger.info(f"   输出: {output_file}")

    update_progress(
        task_id,
        ProgressStep.PPT_OCR,
        0.45,
        f"PPT OCR 完成: {len(results.get('slides', []))} 张幻灯片",
    )

    return {
        "success": True,
        "ocr_result_file": str(output_file),
        "slide_count": len(results.get("slides", [])),
        "error_count": len(results.get("errors", [])),
        "structure_enabled": True,
    }