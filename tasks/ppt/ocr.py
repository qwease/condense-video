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


class PTLOCRError(VideoProcessingException):
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

    Returns:
        OCR 结果信息

    Raises:
        PTLOCRError: OCR 失败
    """
    logger.info(f"开始 PPT OCR 识别: {frames_dir}")

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
            raise PTLOCRError("没有找到可识别的帧")

        # 获取所有帧文件路径
        frames_path = Path(frames_dir)
        frame_images = []

        for frame in frames:
            image_path = frames_path / frame["filename"]
            if image_path.exists():
                frame_images.append({
                    "path": str(image_path),
                    "index": frame["index"],
                    "timestamp": frame["timestamp"],
                })

        if not frame_images:
            raise PTLOCRError("没有找到有效的帧图像文件")

        # 批量 OCR
        client = DashScopeClient(api_key=settings.dashscope_api_key)

        # 使用异步批量 OCR
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            ocr_results = loop.run_until_complete(
                client.ocr_batch(
                    image_urls=[f["path"] for f in frame_images],
                    concurrency=5,
                )
            )
        finally:
            loop.close()

        # 处理 OCR 结果
        slides = []
        for i, (frame_info, ocr_result) in enumerate(zip(frame_images, ocr_results)):
            ocr_text = ocr_result.get("text", "")

            slide_data = {
                "frameId": frame_info["index"],
                "framePath": frame_info["path"],
                "timestamp": frame_info["timestamp"],
                "ocrText": ocr_text,
            }

            # 提取结构化信息
            if structure:
                slide_structure = _extract_structure(ocr_text)
                slide_data["structure"] = slide_structure

            slides.append(slide_data)

            # 更新进度
            progress = 0.3 + (i / len(frame_images)) * 0.15
            update_progress(
                task_id,
                ProgressStep.PPT_OCR,
                progress,
                f"正在识别 PPT: {i + 1}/{len(frame_images)}",
            )

        # 保存 OCR 结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        ocr_result_file = output_path / "ocr_result.json"
        with open(ocr_result_file, "w", encoding="utf-8") as f:
            json.dump({
                "video_info": video_info,
                "slides": slides,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"PPT OCR 识别完成: {len(slides)} 张幻灯片")

        update_progress(
            task_id,
            ProgressStep.PPT_OCR,
            0.45,
            f"PPT OCR 完成: {len(slides)} 张幻灯片",
        )

        return {
            "success": True,
            "ocr_result_file": str(ocr_result_file),
            "slide_count": len(slides),
            "structure_enabled": structure,
        }

    except Exception as e:
        logger.error(f"PPT OCR 识别时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.PPT_OCR,
            0.0,
            f"PPT OCR 失败: {str(e)}",
        )
        raise PTLOCRError(f"PPT OCR 识别失败: {e}")


def _extract_structure(ocr_text: str) -> dict[str, Any]:
    """
    从 OCR 文本中提取结构化信息

    Args:
        ocr_text: OCR 识别的文本

    Returns:
        结构化信息字典
    """
    import re

    lines = ocr_text.split("\n")

    # 过滤空行
    lines = [line.strip() for line in lines if line.strip()]

    if not lines:
        return {
            "title": "",
            "subtitles": [],
            "body": [],
            "formulas": [],
            "keyTerms": [],
            "confidence": 0.0,
        }

    # 提取标题 (通常是第一行，字号较大)
    title = lines[0] if lines else ""

    # 提取副标题 (通常包含 "第X章/节" 等标记)
    subtitles = []
    for line in lines[1:3]:  # 检查前几行
        if re.search(r"第[一二三四五六七八九十\d]+[章节讲]|Chapter|Section|\d+\.", line):
            subtitles.append(line)

    # 提取正文 (除标题副标题外的行)
    body = [line for line in lines if line not in [title] + subtitles]

    # 提取公式 (包含数学符号的行)
    formulas = []
    formula_pattern = r"[A-Z]\([s-zA-Z]\)\s*=\s*[^，。；]+|\([^)]+\)\s*=\s*[^，。；]+"
    for line in body:
        if re.search(formula_pattern, line):
            formulas.append(line)

    # 提取关键词 (出现频率较高或特殊的词)
    key_terms = []
    # 简单实现：提取长度>2且包含专业术语的词
    for line in body[:5]:  # 只检查前几行
        # 查找专业术语模式
        terms = re.findall(r"[\u4e00-\u9fa5]{2,6}", line)
        key_terms.extend(terms[:3])  # 每行最多取3个

    # 去重
    key_terms = list(set(key_terms))[:10]

    # 计算置信度 (基于文本长度和结构完整性)
    confidence = min(1.0, len(ocr_text) / 100)

    return {
        "title": title,
        "subtitles": subtitles,
        "body": body,
        "formulas": formulas,
        "keyTerms": key_terms,
        "confidence": round(confidence, 2),
    }
