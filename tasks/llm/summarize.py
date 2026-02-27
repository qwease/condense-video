"""
内容总结任务

生成课程总结、核心要点和浓缩文稿。
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
from utils.text import (
    create_condensed_text,
    is_filler_sentence,
    is_interaction,
)

logger = setup_logging()


class SummarizationError(VideoProcessingException):
    """内容总结错误"""
    pass


@shared_task(
    name="tasks.llm.summarize",
    bind=True,
    max_retries=2,
)
def summarize_content(
    self,
    task_id: str,
    classification_file: str,
    outline_file: str,
    output_dir: str,
    mode: str = "essential",
) -> dict[str, Any]:
    """
    生成内容总结

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        classification_file: 分类结果文件
        outline_file: 章节大纲文件
        output_dir: 输出目录
        mode: 浓缩模式 (essential=只保留核心, complete=保留核心+解释)

    Returns:
        总结结果信息

    Raises:
        SummarizationError: 总结失败
    """
    logger.info("开始内容总结")

    update_progress(
        task_id,
        ProgressStep.CONTENT_SUMMARIZE,
        0.7,
        "正在生成内容总结...",
    )

    try:
        # 读取数据
        with open(classification_file, "r", encoding="utf-8") as f:
            classification_data = json.load(f)
        segments = classification_data.get("segments", [])

        with open(outline_file, "r", encoding="utf-8") as f:
            outline_data = json.load(f)
        chapters = outline_data.get("chapters", [])

        if not segments:
            raise SummarizationError("没有找到可总结的内容")

        # 确定要保留的分类
        if mode == "essential":
            keep_classes = {"core"}
        elif mode == "complete":
            keep_classes = {"core", "explain"}
        else:
            keep_classes = {"core"}

        # 生成浓缩文本
        condensed_text = _generate_condensed_text(
            segments=segments,
            keep_classes=keep_classes,
        )

        # 使用 LLM 生成总结
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            summary, key_points = loop.run_until_complete(
                _generate_summary_with_llm(
                    chapters=chapters,
                    segments=segments,
                    keep_classes=keep_classes,
                )
            )
        finally:
            loop.close()

        # 保存结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 保存浓缩文本
        condensed_file = output_path / "condensed.txt"
        with open(condensed_file, "w", encoding="utf-8") as f:
            f.write(condensed_text)

        # 保存总结
        summary_file = output_path / "summary.md"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)

        # 保存核心要点
        key_points_file = output_path / "key_points.md"
        with open(key_points_file, "w", encoding="utf-8") as f:
            f.write(key_points)

        logger.info("内容总结完成")

        update_progress(
            task_id,
            ProgressStep.CONTENT_SUMMARIZE,
            0.75,
            "内容总结完成",
        )

        return {
            "success": True,
            "condensed_file": str(condensed_file),
            "summary_file": str(summary_file),
            "key_points_file": str(key_points_file),
            "condensed_length": len(condensed_text),
            "original_length": sum(len(s.get("text", "")) for s in segments),
        }

    except Exception as e:
        logger.error(f"内容总结时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.CONTENT_SUMMARIZE,
            0.0,
            f"内容总结失败: {str(e)}",
        )
        raise SummarizationError(f"内容总结失败: {e}")


def _generate_condensed_text(
    segments: list[dict],
    keep_classes: set,
) -> str:
    """生成浓缩文本"""
    # 过滤片段
    kept_segments = [
        s for s in segments
        if s.get("label") in keep_classes
        and not is_filler_sentence(s.get("text", ""))
        and not is_interaction(s.get("text", ""))
    ]

    # 按时间排序
    kept_segments.sort(key=lambda s: s.get("start_time", 0))

    # 合并文本
    condensed = "".join(s.get("text", "") for s in kept_segments)

    return condensed


async def _generate_summary_with_llm(
    chapters: list[dict],
    segments: list[dict],
    keep_classes: set,
) -> tuple[str, str]:
    """使用 LLM 生成总结和核心要点"""
    client = DashScopeClient(api_key=settings.dashscope_api_key)

    # 为每个章节生成总结
    chapter_summaries = []

    for chapter in chapters:
        chapter_id = chapter.get("id", 0)
        start_idx = chapter.get("start_idx", 0)
        end_idx = chapter.get("end_idx", 0)

        # 获取章节内容
        chapter_segments = [
            s for s in segments
            if start_idx <= s.get("idx", 0) <= end_idx
            and s.get("label") in keep_classes
        ]

        if not chapter_segments:
            continue

        chapter_text = "".join(s.get("text", "") for s in chapter_segments)

        # 生成章节总结
        prompt = f"""请为以下课程内容生成简洁的总结（100字以内）：

{chapter_text}

总结格式：
## {chapter['title']}

[总结内容]
"""

        try:
            summary = await client.generate_text(
                prompt=prompt,
                max_tokens=300,
            )
            chapter_summaries.append(summary)
        except Exception as e:
            logger.warning(f"章节 {chapter_id} 总结生成失败: {e}")
            chapter_summaries.append(f"## {chapter['title']}\n\n{chapter_text[:200]}...")

    # 生成完整总结
    full_summary = "# 课程总结\n\n"
    full_summary += "\n\n".join(chapter_summaries)

    # 生成核心要点
    key_points = "# 核心要点\n\n"

    for chapter in chapters:
        key_points += f"## {chapter['title']}\n\n"

        # 关键公式
        formulas = chapter.get("keyFormulas", [])
        if formulas:
            key_points += "**关键公式**:\n"
            for formula in formulas:
                key_points += f"- `{formula}`\n"
            key_points += "\n"

        # 关键词
        keywords = chapter.get("keywords", [])
        if keywords:
            key_points += "**关键词**: " + ", ".join(keywords[:5]) + "\n\n"

    return full_summary, key_points


@shared_task(
    name="tasks.llm.condense_for_tts",
    bind=True,
)
def condense_for_tts(
    self,
    task_id: str,
    classification_file: str,
    output_dir: str,
    mode: str = "essential",
) -> dict[str, Any]:
    """
    生成适合 TTS 的浓缩文本

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        classification_file: 分类结果文件
        output_dir: 输出目录
        mode: 浓缩模式

    Returns:
        浓缩文本信息
    """
    logger.info("生成 TTS 浓缩文本")

    try:
        with open(classification_file, "r", encoding="utf-8") as f:
            classification_data = json.load(f)
        segments = classification_data.get("segments", [])

        # 确定保留分类
        keep_classes = {"core"} if mode == "essential" else {"core", "explain"}

        # 生成浓缩文本
        condensed_text = _generate_condensed_text(
            segments=segments,
            keep_classes=keep_classes,
        )

        # 添加过渡词以保持流畅
        condensed_text = _add_transitions(condensed_text)

        # 保存
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        condensed_file = output_path / "condensed_for_tts.txt"
        with open(condensed_file, "w", encoding="utf-8") as f:
            f.write(condensed_text)

        # 同时保存为 JSON 格式（带时间信息）
        condensed_json = _create_condensed_json(
            segments=segments,
            keep_classes=keep_classes,
        )

        json_file = output_path / "condensed.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(condensed_json, f, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "condensed_file": str(condensed_file),
            "json_file": str(json_file),
            "text_length": len(condensed_text),
            "segment_count": len(condensed_json.get("segments", [])),
        }

    except Exception as e:
        logger.error(f"生成 TTS 浓缩文本时发生错误: {e}")
        raise SummarizationError(f"生成 TTS 浓缩文本失败: {e}")


def _add_transitions(text: str) -> str:
    """添加过渡词"""
    # 简单实现：在长文本中适当添加过渡
    import re

    # 在长句后添加过渡
    sentences = re.split(r"(。|！|？|\.)", text)
    result = []

    for i, sentence in enumerate(sentences):
        result.append(sentence)
        # 每3-5句添加一次过渡
        if i > 0 and i % 4 == 0 and sentence.strip():
            result.append("此外，")

    return "".join(result)


def _create_condensed_json(
    segments: list[dict],
    keep_classes: set,
) -> dict:
    """创建浓缩文本 JSON（保留时间信息）"""
    condensed_segments = [
        {
            "idx": s.get("idx"),
            "text": s.get("text", ""),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "label": s.get("label"),
        }
        for s in segments
        if s.get("label") in keep_classes
        and not is_filler_sentence(s.get("text", ""))
        and not is_interaction(s.get("text", ""))
    ]

    return {
        "segments": condensed_segments,
        "total_duration": sum(
            s.get("end_time", 0) - s.get("start_time", 0)
            for s in condensed_segments
        ),
    }
