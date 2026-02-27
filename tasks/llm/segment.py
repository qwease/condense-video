"""
章节切分任务

基于 PPT 切换和内容聚类，将课程内容切分为章节。
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


class SegmentationError(VideoProcessingException):
    """章节切分错误"""
    pass


@shared_task(
    name="tasks.llm.segment",
    bind=True,
)
def segment_chapters(
    self,
    task_id: str,
    classification_file: str,
    ocr_result_file: str,
    sentences_file: str,
    output_dir: str,
) -> dict[str, Any]:
    """
    切分课程章节

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        classification_file: 分类结果文件
        ocr_result_file: OCR 结果文件
        sentences_file: 句子文件
        output_dir: 输出目录

    Returns:
        章节切分结果

    Raises:
        SegmentationError: 切分失败
    """
    logger.info("开始章节切分")

    update_progress(
        task_id,
        ProgressStep.CHAPTER_SEGMENT,
        0.6,
        "正在进行章节切分...",
    )

    try:
        # 读取数据
        with open(classification_file, "r", encoding="utf-8") as f:
            classification_data = json.load(f)
        segments = classification_data.get("segments", [])

        with open(ocr_result_file, "r", encoding="utf-8") as f:
            ocr_data = json.load(f)
        ppt_slides = ocr_data.get("slides", [])

        if not segments:
            raise SegmentationError("没有找到可切分的片段")

        # 基于 PPT 切换切分章节
        chapters = _segment_by_ppt(
            segments=segments,
            ppt_slides=ppt_slides,
        )

        # 提取关键信息
        _extract_chapter_keywords(chapters)

        # 保存结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 保存 JSON
        outline_file = output_path / "outline.json"
        with open(outline_file, "w", encoding="utf-8") as f:
            json.dump({
                "title": _extract_course_title(ppt_slides),
                "total_duration": sum(c.get("duration", 0) for c in chapters),
                "total_sentences": len(segments),
                "chapters": chapters,
            }, f, ensure_ascii=False, indent=2)

        # 生成 Markdown 大纲
        _generate_outline_markdown(
            chapters=chapters,
            output_path=output_path,
        )

        logger.info(f"章节切分完成: {len(chapters)} 个章节")

        update_progress(
            task_id,
            ProgressStep.CHAPTER_SEGMENT,
            0.65,
            f"章节切分完成: {len(chapters)} 个章节",
        )

        return {
            "success": True,
            "outline_file": str(outline_file),
            "chapter_count": len(chapters),
        }

    except Exception as e:
        logger.error(f"章节切分时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.CHAPTER_SEGMENT,
            0.0,
            f"章节切分失败: {str(e)}",
        )
        raise SegmentationError(f"章节切分失败: {e}")


def _segment_by_ppt(
    segments: list[dict],
    ppt_slides: list[dict],
) -> list[dict]:
    """基于 PPT 切换切分章节"""
    if not ppt_slides:
        # 没有 PPT 信息，整个内容作为一章
        return [_create_single_chapter(segments)]

    chapters = []
    current_chapter_segments = []
    current_ppt = ppt_slides[0]

    for segment in segments:
        segment_time = segment.get("start_time", 0)

        # 检查是否切换到新的 PPT
        new_ppt = _find_ppt_at_time(segment_time, ppt_slides)

        if new_ppt != current_ppt and current_chapter_segments:
            # PPT 切换，结束当前章节
            chapters.append(_create_chapter(
                segments=current_chapter_segments,
                ppt=current_ppt,
                chapter_id=len(chapters) + 1,
            ))
            current_chapter_segments = []
            current_ppt = new_ppt

        current_chapter_segments.append(segment)

    # 处理最后一章
    if current_chapter_segments:
        chapters.append(_create_chapter(
            segments=current_chapter_segments,
            ppt=current_ppt,
            chapter_id=len(chapters) + 1,
        ))

    return chapters


def _find_ppt_at_time(
    timestamp: float,
    ppt_slides: list[dict],
) -> dict | None:
    """查找指定时间对应的 PPT"""
    for slide in ppt_slides:
        slide_time = slide.get("timestamp", 0)
        if slide_time <= timestamp:
            return slide
    return None


def _create_chapter(
    segments: list[dict],
    ppt: dict | None,
    chapter_id: int,
) -> dict:
    """创建章节数据"""
    if not segments:
        return {}

    # 从 PPT 提取标题
    structure = ppt.get("structure", {}) if ppt else {}
    title = structure.get("title", f"第{chapter_id}章")
    if not title:
        title = f"第{chapter_id}章"

    # 提取核心公式
    formulas = structure.get("formulas", []) if ppt else []

    # 计算时间范围
    start_time = min(s.get("start_time", 0) for s in segments)
    end_time = max(s.get("end_time", 0) for s in segments)

    # 统计核心句子
    core_count = sum(
        1 for s in segments
        if s.get("label") in ["core", "explain"]
    )

    return {
        "id": chapter_id,
        "title": title,
        "start_slide": ppt.get("frameId", 0) if ppt else 0,
        "end_slide": ppt.get("frameId", 0) if ppt else 0,
        "start_idx": segments[0].get("idx", 0),
        "end_idx": segments[-1].get("idx", 0),
        "start_time": start_time,
        "end_time": end_time,
        "duration": end_time - start_time,
        "core_sentences": core_count,
        "total_sentences": len(segments),
        "keywords": structure.get("keyTerms", []) if ppt else [],
        "keyFormulas": formulas,
    }


def _create_single_chapter(segments: list[dict]) -> dict:
    """创建单章（没有 PPT 信息时）"""
    if not segments:
        return {}

    start_time = min(s.get("start_time", 0) for s in segments)
    end_time = max(s.get("end_time", 0) for s in segments)

    return {
        "id": 1,
        "title": "课程内容",
        "start_slide": 0,
        "end_slide": 0,
        "start_idx": segments[0].get("idx", 0),
        "end_idx": segments[-1].get("idx", 0),
        "start_time": start_time,
        "end_time": end_time,
        "duration": end_time - start_time,
        "core_sentences": sum(
            1 for s in segments
            if s.get("label") in ["core", "explain"]
        ),
        "total_sentences": len(segments),
        "keywords": [],
        "keyFormulas": [],
    }


def _extract_chapter_keywords(chapters: list[dict]):
    """提取章节关键词"""
    # 简单实现：从标题和公式中提取关键词
    for chapter in chapters:
        keywords = chapter.get("keywords", [])
        title = chapter.get("title", "")

        # 从标题提取
        import re
        title_terms = re.findall(r"[\u4e00-\u9fa5]{2,6}", title)
        keywords.extend(title_terms)

        # 去重
        chapter["keywords"] = list(set(keywords))[:10]


def _extract_course_title(ppt_slides: list[dict]) -> str:
    """提取课程标题"""
    if not ppt_slides:
        return "课程"

    # 从第一张 PPT 提取
    first_ppt = ppt_slides[0]
    structure = first_ppt.get("structure", {})

    # 检查是否是标题页（包含"章"、"课程"等）
    title = structure.get("title", "")
    if any(keyword in title for keyword in ["第", "章", "课程", "Chapter"]):
        return title

    return "课程"


def _generate_outline_markdown(
    chapters: list[dict],
    output_path: Path,
):
    """生成大纲 Markdown"""
    lines = [
        "# 课程大纲\n",
    ]

    total_duration = sum(c.get("duration", 0) for c in chapters)

    lines.append(f"**总时长**: {total_duration / 60:.1f} 分钟")
    lines.append(f"**章节数**: {len(chapters)}\n")

    for chapter in chapters:
        lines.append(f"## {chapter['title']}\n")
        lines.append(f"- 时长: {chapter['duration'] / 60:.1f} 分钟")
        lines.append(f"- 核心句子: {chapter['core_sentences']}/{chapter['total_sentences']}")

        if chapter.get("keyFormulas"):
            lines.append("\n**关键公式**:")
            for formula in chapter["keyFormulas"]:
                lines.append(f"- `{formula}`")

        if chapter.get("keywords"):
            lines.append("\n**关键词**:")
            lines.append(", ".join(chapter["keywords"][:5]))

        lines.append("")

    outline_file = output_path / "outline.md"
    with open(outline_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
