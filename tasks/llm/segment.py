"""
章节切分任务

基于 PPT 切换和内容聚类，将课程内容切分为章节。

功能：
1. 基于 PPT 切换自动切分章节
2. 提取章节关键词、公式
3. 生成 outline.json 和 outline.md
"""

import json
import re
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
        classification_file: 分类结果文件 (classification.json)
        ocr_result_file: OCR 结果文件 (slides.json 或 ocr_result.json)
        sentences_file: 句子文件 (sentences.txt)
        output_dir: 输出目录

    Returns:
        章节切分结果

    Raises:
        SegmentationError: 切分失败
    """
    logger.info("🔖 开始章节切分")

    update_progress(
        task_id,
        ProgressStep.CHAPTER_SEGMENT,
        0.6,
        "正在进行章节切分...",
    )

    try:
        # 读取分类结果
        with open(classification_file, "r", encoding="utf-8") as f:
            classification_data = json.load(f)
        segments = classification_data.get("segments", [])

        # 读取 OCR 结果 (如果存在)
        ppt_slides = []
        ocr_result_path = Path(ocr_result_file)
        if ocr_result_path.exists():
            with open(ocr_result_file, "r", encoding="utf-8") as f:
                ocr_data = json.load(f)
                ppt_slides = ocr_data.get("slides", [])
            logger.info(f"📊 加载 {len(ppt_slides)} 个 PPT 帧")
        else:
            logger.warning(f"OCR 结果文件不存在，跳过 PPT 对齐: {ocr_result_file}")

        if not segments:
            raise SegmentationError("没有找到可切分的片段")

        # 基于 PPT 切换切分章节
        chapters = _segment_by_ppt(
            segments=segments,
            ppt_slides=ppt_slides,
        )

        logger.info(f"初步切分为 {len(chapters)} 个章节")

        # 提取关键信息
        _extract_chapter_keywords(chapters)

        # 保存结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 提取课程标题
        course_title = _extract_course_title(ppt_slides)

        # 计算总时长
        total_duration = sum(c.get("duration", 0) for c in chapters)

        # 保存 JSON
        outline_file = output_path / "outline.json"
        with open(outline_file, "w", encoding="utf-8") as f:
            json.dump({
                "title": course_title,
                "total_duration": total_duration,
                "total_sentences": len(segments),
                "chapter_count": len(chapters),
                "chapters": chapters,
            }, f, ensure_ascii=False, indent=2)

        # 生成 Markdown 大纲
        _generate_outline_markdown(
            chapters=chapters,
            course_title=course_title,
            total_duration=total_duration,
            output_path=output_path,
        )

        logger.info(f"✅ 章节切分完成: {len(chapters)} 个章节")

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
            "total_duration": total_duration,
        }

    except Exception as e:
        logger.error(f"章节切分时发生错误: {e}", exc_info=True)
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
    """
    基于 PPT 切换切分章节
    
    策略：每当 PPT 切换时，创建新章节
    """
    if not ppt_slides:
        # 没有 PPT 信息，整个内容作为一章
        logger.info("无 PPT 信息，创建单章节")
        return [_create_single_chapter(segments)]

    chapters = []
    current_chapter_segments = []
    current_ppt = None

    for segment in segments:
        segment_time = segment.get("start_time", 0)

        # 查找当前时间对应的 PPT
        new_ppt = _find_ppt_at_time(segment_time, ppt_slides)

        # 检查是否切换到新的 PPT
        if new_ppt != current_ppt:
            # PPT 切换，结束当前章节（如果有内容）
            if current_chapter_segments:
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
    """
    查找指定时间对应的 PPT
    
    策略：找到时间戳小于等于当前时间的最后一个 PPT
    """
    matched_slide = None
    for slide in ppt_slides:
        slide_time = slide.get("timestamp", 0)
        if slide_time <= timestamp:
            matched_slide = slide
        else:
            # 超过当前时间，停止查找
            break
    
    return matched_slide


def _create_chapter(
    segments: list[dict],
    ppt: dict | None,
    chapter_id: int,
) -> dict:
    """
    创建章节数据
    
    Args:
        segments: 章节包含的句子片段
        ppt: 对应的 PPT 幻灯片
        chapter_id: 章节编号
        
    Returns:
        章节数据字典
    """
    if not segments:
        return {}

    # 从 PPT 提取标题
    structure = ppt.get("structure", {}) if ppt else {}
    title = structure.get("title", f"第{chapter_id}章")
    if not title or title.strip() == "":
        title = f"第{chapter_id}章"

    # 提取核心公式
    formulas = structure.get("formulas", []) if ppt else []

    # 计算时间范围（安全处理 None）
    start_times = [s.get("start_time") for s in segments if s.get("start_time") is not None]
    end_times = [s.get("end_time") for s in segments if s.get("end_time") is not None]
    
    start_time = min(start_times) if start_times else 0
    end_time = max(end_times) if end_times else 0

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
    """
    创建单章（没有 PPT 信息时）
    
    Args:
        segments: 所有句子片段
        
    Returns:
        单章节数据
    """
    if not segments:
        return {
            "id": 1,
            "title": "课程内容",
            "start_slide": 0,
            "end_slide": 0,
            "start_idx": 0,
            "end_idx": 0,
            "start_time": 0,
            "end_time": 0,
            "duration": 0,
            "core_sentences": 0,
            "total_sentences": 0,
            "keywords": [],
            "keyFormulas": [],
        }

    # 安全获取时间
    start_times = [s.get("start_time") for s in segments if s.get("start_time") is not None]
    end_times = [s.get("end_time") for s in segments if s.get("end_time") is not None]
    
    start_time = min(start_times) if start_times else 0
    end_time = max(end_times) if end_times else 0

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
    """
    提取章节关键词
    
    策略：
    1. 使用 PPT 的 keyTerms
    2. 从标题中提取中文专业术语（2-6字）
    3. 去重并限制数量
    """
    for chapter in chapters:
        keywords = list(chapter.get("keywords", []))  # 复制 PPT 关键词
        title = chapter.get("title", "")

        # 从标题提取中文术语（2-6字）
        title_terms = re.findall(r"[\u4e00-\u9fa5]{2,6}", title)
        keywords.extend(title_terms)

        # 去重并限制数量
        unique_keywords = []
        seen = set()
        for kw in keywords:
            if kw not in seen:
                unique_keywords.append(kw)
                seen.add(kw)
        
        chapter["keywords"] = unique_keywords[:10]  # 最多10个


def _extract_course_title(ppt_slides: list[dict]) -> str:
    """
    提取课程标题
    
    策略：
    1. 从第一张 PPT 的标题提取
    2. 检查是否包含"章"、"课程"等关键词
    3. 默认返回"课程"
    """
    if not ppt_slides:
        return "课程"

    # 从第一张 PPT 提取
    first_ppt = ppt_slides[0]
    structure = first_ppt.get("structure", {})
    title = structure.get("title", "")

    # 检查是否是标题页
    if title and any(keyword in title for keyword in ["第", "章", "课程", "Chapter", "Lecture"]):
        return title

    # 默认
    return title if title else "课程"


def _generate_outline_markdown(
    chapters: list[dict],
    course_title: str,
    total_duration: float,
    output_path: Path,
):
    """
    生成大纲 Markdown
    
    格式：
    # 课程大纲
    **总时长**: X 分钟
    **章节数**: X
    
    ## 章节标题
    - 时长: X 分钟
    - 核心句子: X/Y
    - 关键公式: ...
    - 关键词: ...
    """
    lines = [
        f"# {course_title}\n",
        f"**总时长**: {total_duration / 60:.1f} 分钟  ",
        f"**章节数**: {len(chapters)}\n",
    ]

    for chapter in chapters:
        lines.append(f"## {chapter['title']}\n")
        
        # 时长和句子统计
        lines.append(f"- **时长**: {chapter['duration'] / 60:.1f} 分钟")
        lines.append(f"- **核心句子**: {chapter['core_sentences']}/{chapter['total_sentences']}")

        # 关键公式
        if chapter.get("keyFormulas"):
            lines.append("\n**关键公式**:")
            for formula in chapter["keyFormulas"]:
                # 简单清理公式文本
                formula_clean = formula.strip()
                lines.append(f"- {formula_clean}")

        # 关键词
        if chapter.get("keywords"):
            lines.append(f"\n**关键词**: {', '.join(chapter['keywords'][:5])}")

        lines.append("")  # 空行分隔

    # 保存文件
    outline_md_file = output_path / "outline.md"
    with open(outline_md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    logger.info(f"已生成大纲 Markdown: {outline_md_file}")