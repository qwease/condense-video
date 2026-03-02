"""
内容浓缩任务

使用 LLM 浓缩章节内容，生成精讲文稿。

功能:
1. 使用 DashScope Qwen-Plus 浓缩章节内容
2. 保持教师语言风格
3. 分段生成，自然衔接
4. 输出精讲文稿、总结、核心要点
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from datetime import datetime

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.dashscope import DashScopeClient
from services.redis_client import update_progress
from utils.text import (
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
    target_duration: int = 150,  # 每章目标时长（秒）
    resume: bool = True,
) -> dict[str, Any]:
    """
    生成内容总结和浓缩文稿

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        classification_file: 分类结果文件
        outline_file: 章节大纲文件
        output_dir: 输出目录
        mode: 浓缩模式 (essential=只保留核心, complete=保留核心+解释)
        target_duration: 每章目标时长（秒）
        resume: 是否支持断点续传

    Returns:
        总结结果信息

    Raises:
        SummarizationError: 总结失败
    """
    logger.info("✍️ 开始内容浓缩")

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

        logger.info(f"📚 加载 {len(chapters)} 个章节, {len(segments)} 个片段")

        # 确定要保留的分类
        keep_classes = {"core"} if mode == "essential" else {"core", "explain"}

        # 准备章节数据（提取核心语音和 PPT 内容）
        chapter_contents = _prepare_chapter_contents(
            chapters=chapters,
            segments=segments,
            keep_classes=keep_classes,
        )

        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 检查断点续传
        condensed_file = output_path / "condensed.json"
        scripts = []
        processed_ids = set()

        if resume and condensed_file.exists():
            with open(condensed_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                scripts = existing_data.get("scripts", [])
                processed_ids = {s["chapterId"] for s in scripts}
            logger.info(f"📂 已加载 {len(scripts)} 个已完成的文稿")

        # 待处理章节
        pending_chapters = [
            ch for ch in chapter_contents
            if ch["id"] not in processed_ids
        ]
        logger.info(f"📊 待处理: {len(pending_chapters)} 个章节")

        if pending_chapters:
            # 使用 LLM 生成浓缩文稿
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            new_scripts = loop.run_until_complete(
                _generate_condensed_scripts(
                    chapters=pending_chapters,
                    target_duration=target_duration,
                    task_id=task_id,
                    output_path=output_path,
                    existing_scripts=scripts,
                )
            )

            scripts.extend(new_scripts)

        # 保存最终结果
        total_duration = sum(s["targetDuration"] for s in scripts)
        total_words = sum(s["wordCount"] for s in scripts)

        condensed_data = {
            "generatedAt": datetime.now().isoformat(),
            "modelUsed": settings.dashscope_llm_model,
            "totalDuration": total_duration,
            "totalWords": total_words,
            "scripts": scripts,
        }

        with open(condensed_file, "w", encoding="utf-8") as f:
            json.dump(condensed_data, f, ensure_ascii=False, indent=2)

        # 生成纯文本文稿
        _generate_text_scripts(scripts, output_path)

        # 生成总结和要点
        _generate_summary_and_keypoints(chapters, scripts, output_path)

        logger.info(f"\n✅ 浓缩完成！")
        logger.info(f"   总章节数: {len(scripts)}")
        logger.info(f"   总字数: {total_words}")
        logger.info(f"   预计时长: {total_duration / 60:.1f} 分钟")

        update_progress(
            task_id,
            ProgressStep.CONTENT_SUMMARIZE,
            0.75,
            "内容总结完成",
        )

        return {
            "success": True,
            "condensed_file": str(condensed_file),
            "script_count": len(scripts),
            "total_words": total_words,
            "total_duration": total_duration,
        }

    except Exception as e:
        logger.error(f"内容总结时发生错误: {e}", exc_info=True)
        update_progress(
            task_id,
            ProgressStep.CONTENT_SUMMARIZE,
            0.0,
            f"内容总结失败: {str(e)}",
        )
        raise SummarizationError(f"内容总结失败: {e}")


def _prepare_chapter_contents(
    chapters: list[dict],
    segments: list[dict],
    keep_classes: set,
) -> list[dict]:
    """
    准备章节内容数据
    
    为每个章节提取：
    1. 核心语音（过滤后的片段文本）
    2. PPT 内容（标题、公式、关键词）
    """
    chapter_contents = []

    for chapter in chapters:
        chapter_id = chapter.get("id", 0)
        start_idx = chapter.get("start_idx", 0)
        end_idx = chapter.get("end_idx", 0)

        # 获取章节内核心片段
        chapter_segments = [
            s for s in segments
            if start_idx <= s.get("idx", 0) <= end_idx
            and s.get("label") in keep_classes
            and not is_filler_sentence(s.get("text", ""))
            and not is_interaction(s.get("text", ""))
        ]

        # 合并为核心语音
        core_speech = "".join(s.get("text", "") for s in chapter_segments)

        # PPT 内容
        slide_content = {
            "title": chapter.get("title", ""),
            "formulas": chapter.get("keyFormulas", []),
            "keywords": chapter.get("keywords", []),
        }

        chapter_contents.append({
            "id": chapter_id,
            "title": chapter.get("title", ""),
            "coreSpeech": core_speech,
            "slideContent": slide_content,
            "duration": chapter.get("duration", 0),
        })

    return chapter_contents


async def _generate_condensed_scripts(
    chapters: list[dict],
    target_duration: int,
    task_id: str,
    output_path: Path,
    existing_scripts: list[dict],
) -> list[dict]:
    """
    生成浓缩文稿（异步批量处理）
    """
    client = DashScopeClient(api_key=settings.dashscope_api_key)
    scripts = []

    # 获取上一章的过渡文本
    previous_transition = ""
    if existing_scripts:
        previous_transition = existing_scripts[-1].get("transitionOut", "")

    for i, chapter in enumerate(chapters):
        logger.info(
            f"\n📝 [{i + 1}/{len(chapters)}] 处理章节 {chapter['id']}: "
            f"{chapter['title'][:30]}..."
        )

        script = await _generate_chapter_script(
            chapter=chapter,
            previous_transition=previous_transition,
            target_duration=target_duration,
            client=client,
        )

        scripts.append(script)
        previous_transition = script.get("transitionOut", "")

        logger.info(f"   ✅ 生成完成: {script['wordCount']} 字")

        # 更新进度
        progress = 0.7 + ((i + 1) / len(chapters)) * 0.05
        update_progress(
            task_id,
            ProgressStep.CONTENT_SUMMARIZE,
            progress,
            f"正在浓缩: {i + 1}/{len(chapters)}",
        )

        # 每 3 章保存一次
        if (i + 1) % 3 == 0:
            _save_intermediate_scripts(
                scripts=existing_scripts + scripts,
                output_path=output_path,
            )

    return scripts


async def _generate_chapter_script(
    chapter: dict,
    previous_transition: str,
    target_duration: int,
    client: DashScopeClient,
) -> dict:
    """
    生成单章浓缩文稿
    
    Args:
        chapter: 章节数据
        previous_transition: 上一章的过渡文本
        target_duration: 目标时长（秒）
        client: DashScope 客户端
        
    Returns:
        浓缩文稿数据
    """
    # 格式化 PPT 内容
    slide_content = _format_slide_content(chapter["slideContent"])

    # 构建 prompt
    prompt = _build_condensation_prompt(
        chapter_title=chapter["title"],
        slide_content=slide_content,
        core_speech=chapter["coreSpeech"],
        previous_transition=previous_transition,
        target_duration=target_duration,
    )

    try:
        response = await client.generate_text(
            prompt=prompt,
            max_tokens=2048,
            temperature=0.4,
        )

        return _parse_script_response(response, chapter, target_duration)

    except Exception as e:
        logger.error(f"章节 {chapter['id']} 生成失败: {e}")
        # 降级：使用原始语音
        return {
            "chapterId": chapter["id"],
            "title": chapter["title"],
            "script": chapter["coreSpeech"],
            "keyPoints": [],
            "transitionOut": "",
            "targetDuration": target_duration,
            "wordCount": len(chapter["coreSpeech"]),
            "error": str(e),
        }


def _format_slide_content(slide_content: dict) -> str:
    """格式化 PPT 内容为文本"""
    lines = []

    title = slide_content.get("title", "")
    if title:
        lines.append(f"标题: {title}")

    formulas = slide_content.get("formulas", [])
    if formulas:
        lines.append("\n关键公式:")
        for formula in formulas:
            lines.append(f"- {formula}")

    keywords = slide_content.get("keywords", [])
    if keywords:
        lines.append(f"\n关键词: {', '.join(keywords)}")

    return "\n".join(lines) if lines else "无 PPT 内容"


def _build_condensation_prompt(
    chapter_title: str,
    slide_content: str,
    core_speech: str,
    previous_transition: str,
    target_duration: int,
) -> str:
    """构建浓缩 prompt"""
    prompt = f"""你是一位优秀的课程内容编辑，负责将课堂录音浓缩为精讲文稿。

## 任务
将以下章节内容浓缩为 {target_duration} 秒（约 {target_duration * 3} 字）的精讲文稿。

## 章节信息
**标题**: {chapter_title}

**PPT 内容**:
{slide_content}

**核心语音**:
{core_speech[:1000]}...

{f"**上一章过渡**: {previous_transition}" if previous_transition else ""}

## 要求
1. **保持教师语言风格**：口语化、自然流畅
2. **保留核心知识点**：定义、公式、定理
3. **自然衔接**：与上一章内容承接
4. **目标时长**：约 {target_duration} 秒（{target_duration * 3} 字）
5. **提取要点**：列出 3-5 个核心知识点

## 输出格式
请返回 JSON 格式：

```json
{{
  "script": "浓缩后的精讲文稿...",
  "keyPoints": ["要点1", "要点2", "要点3"],
  "transitionOut": "本章结尾的过渡语，用于衔接下一章"
}}
```

请直接返回 JSON，不要有其他说明文字。
"""
    return prompt


def _parse_script_response(
    response: str,
    chapter: dict,
    target_duration: int,
) -> dict:
    """解析 LLM 响应"""
    try:
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            parsed = json.loads(json_match.group(0))
            return {
                "chapterId": chapter["id"],
                "title": chapter["title"],
                "script": parsed.get("script", ""),
                "keyPoints": parsed.get("keyPoints", []),
                "transitionOut": parsed.get("transitionOut", ""),
                "targetDuration": target_duration,
                "wordCount": len(parsed.get("script", "")),
            }
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败，使用原始文本: {e}")

    # 降级：使用原始文本
    return {
        "chapterId": chapter["id"],
        "title": chapter["title"],
        "script": response,
        "keyPoints": [],
        "transitionOut": "",
        "targetDuration": target_duration,
        "wordCount": len(response),
    }


def _save_intermediate_scripts(scripts: list[dict], output_path: Path):
    """保存中间结果（支持断点续传）"""
    condensed_file = output_path / "condensed.json"
    
    total_duration = sum(s["targetDuration"] for s in scripts)
    total_words = sum(s["wordCount"] for s in scripts)

    data = {
        "generatedAt": datetime.now().isoformat(),
        "modelUsed": settings.dashscope_llm_model,
        "totalDuration": total_duration,
        "totalWords": total_words,
        "scripts": scripts,
    }

    with open(condensed_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_text_scripts(scripts: list[dict], output_path: Path):
    """生成纯文本文稿"""
    lines = []

    for script in scripts:
        lines.append(f"# {script['title']}\n")
        lines.append(script["script"])
        lines.append("\n---\n")

    condensed_txt = output_path / "condensed.txt"
    with open(condensed_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_summary_and_keypoints(
    chapters: list[dict],
    scripts: list[dict],
    output_path: Path,
):
    """生成总结和核心要点"""
    # 生成总结
    summary_lines = ["# 课程总结\n"]

    for script in scripts:
        summary_lines.append(f"## {script['title']}\n")
        summary_lines.append(script["script"][:200] + "...\n")

    summary_file = output_path / "summary.md"
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    # 生成核心要点
    keypoints_lines = ["# 核心要点\n"]

    for script in scripts:
        keypoints_lines.append(f"## {script['title']}\n")

        # 要点
        if script.get("keyPoints"):
            for point in script["keyPoints"]:
                keypoints_lines.append(f"- {point}")
            keypoints_lines.append("")

    keypoints_file = output_path / "key_points.md"
    with open(keypoints_file, "w", encoding="utf-8") as f:
        f.write("\n".join(keypoints_lines))


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
        # 检查是否已有 condensed.json（由 summarize_content 生成）
        output_path = Path(output_dir)
        condensed_json_file = output_path / "condensed.json"

        if condensed_json_file.exists():
            # 使用已生成的浓缩文稿
            with open(condensed_json_file, "r", encoding="utf-8") as f:
                condensed_data = json.load(f)
            scripts = condensed_data.get("scripts", [])

            logger.info(f"使用已生成的浓缩文稿: {len(scripts)} 个章节")

        else:
            # 降级：使用简单的片段拼接
            with open(classification_file, "r", encoding="utf-8") as f:
                classification_data = json.load(f)
            segments = classification_data.get("segments", [])

            keep_classes = {"core"} if mode == "essential" else {"core", "explain"}

            kept_segments = [
                s for s in segments
                if s.get("label") in keep_classes
                and not is_filler_sentence(s.get("text", ""))
                and not is_interaction(s.get("text", ""))
            ]

            logger.info(f"使用简单拼接: {len(kept_segments)} 个片段")

        return {
            "success": True,
            "condensed_file": str(condensed_json_file),
            "text_length": len("".join(s["script"] for s in scripts)),
        }

    except Exception as e:
        logger.error(f"生成 TTS 浓缩文本失败: {e}", exc_info=True)
        raise SummarizationError(f"生成 TTS 浓缩文本失败: {e}")