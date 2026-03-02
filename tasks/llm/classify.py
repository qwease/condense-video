"""
内容分类任务（语音 + PPT 融合）

功能：
1. 加载语音转录结果和 PPT OCR 结果
2. 时间对齐，交叉验证
3. 快速规则预判 + AI 分类
4. 并发处理 + 限流
5. 输出分类结果

输入: subtitles_words.json, sentences.txt, slides.json
输出: segments.json (classification.json), classification.md
"""

import asyncio
import json
import re
from enum import Enum
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


class ClassificationLabel(str, Enum):
    """内容分类标签"""
    CORE = "core"              # 核心知识，必留
    EXPLAIN = "explain"        # 解释说明，可选
    INTERACT = "interact"      # 课堂互动，建议删
    CHAT = "chat"              # 闲聊跑题，必删
    TRANSITION = "transition"  # 过渡语，可删


class ClassificationError(VideoProcessingException):
    """内容分类错误"""
    pass


@shared_task(
    name="tasks.llm.classify",
    bind=True,
    max_retries=2,
)
def classify_content(
    self,
    task_id: str,
    sentences_file: str,
    ocr_result_file: str,
    output_dir: str,
    concurrency: int = 10,
    resume: bool = True,
) -> dict[str, Any]:
    """
    对转录内容进行分类（融合 PPT 信息）

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        sentences_file: 句子文件路径 (sentences.txt)
        ocr_result_file: OCR 结果文件路径 (slides.json 或 ocr_result.json)
        output_dir: 输出目录
        concurrency: 并发数
        resume: 是否支持断点续传

    Returns:
        分类结果信息

    Raises:
        ClassificationError: 分类失败
    """
    logger.info("🏷️ 开始内容分类（语音 + PPT 融合）")
    logger.info(f"📁 句子文件: {sentences_file}")
    logger.info(f"📁 OCR 文件: {ocr_result_file}")

    update_progress(
        task_id,
        ProgressStep.CONTENT_CLASSIFY,
        0.45,
        "正在进行内容分类...",
    )

    try:
        # 加载数据
        data = _load_data(sentences_file, ocr_result_file)
        sentences = data["sentences"]
        slides = data["slides"]
        words = data["words"]

        logger.info(f"📝 加载 {len(sentences)} 个句子")
        logger.info(f"📊 加载 {len(slides)} 个 PPT 帧")
        logger.info(f"📝 加载 {len(words)} 个字幕元素")

        if not sentences:
            # 创建空分类结果
            return _save_empty_results(output_dir, task_id)

        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 检查断点续传
        results_file = output_path / "classification.json"
        segments_file = output_path / "segments.json"  # 兼容 JS 版本
        
        results = []
        if resume and segments_file.exists():
            with open(segments_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            logger.info(f"📂 已加载 {len(results)} 个已完成的结果")

            if len(results) == len(sentences):
                logger.info("✅ 所有句子已分类完成")
                return _finalize_results(results, output_path, task_id)

        # 执行批量分类
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        results = loop.run_until_complete(
            _classify_batch(
                sentences=sentences,
                slides=slides,
                words=words,
                concurrency=concurrency,
                task_id=task_id,
                output_path=output_path,
            )
        )

        return _finalize_results(results, output_path, task_id)

    except Exception as e:
        logger.error(f"内容分类时发生错误: {e}", exc_info=True)
        update_progress(
            task_id,
            ProgressStep.CONTENT_CLASSIFY,
            0.0,
            f"内容分类失败: {str(e)}",
        )
        raise ClassificationError(f"内容分类失败: {e}")


def _load_data(sentences_file: str, ocr_result_file: str) -> dict[str, Any]:
    """
    加载数据（参考 JS 的 loadData 函数）
    
    Args:
        sentences_file: 句子文件路径
        ocr_result_file: OCR 结果文件路径
        
    Returns:
        包含 sentences, slides, words 的字典
    """
    data = {
        "words": [],
        "sentences": [],
        "slides": [],
    }

    sentences_path = Path(sentences_file)
    
    # 加载字幕词（用于获取精确时间）
    subtitles_path = sentences_path.parent / "subtitles_words.json"
    if subtitles_path.exists():
        with open(subtitles_path, "r", encoding="utf-8") as f:
            subtitles_data = json.load(f)
            # 可能是 {"subtitles_words": [...]} 或直接是数组
            if isinstance(subtitles_data, list):
                data["words"] = subtitles_data
            else:
                data["words"] = subtitles_data.get("subtitles_words", 
                               subtitles_data.get("words", []))

    # 加载句子
    if sentences_path.exists():
        if sentences_path.suffix == ".json":
            with open(sentences_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
                data["sentences"] = json_data.get("sentences", json_data if isinstance(json_data, list) else [])
        elif sentences_path.suffix == ".txt":
            # 解析 sentences.txt 格式: idx|start_time-end_time|text
            # 示例: 0|0.000-70.960|这是句子内容
            with open(sentences_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    parts = line.split("|")
                    if len(parts) >= 3:
                        idx = int(parts[0])
                        time_range = parts[1]
                        text = parts[2]
                        
                        # 解析 start_time-end_time（浮点数秒）
                        start_time = 0.0
                        end_time = 0.0
                        if "-" in time_range:
                            start_str, end_str = time_range.split("-", 1)
                            try:
                                start_time = float(start_str)
                                end_time = float(end_str)
                            except ValueError:
                                logger.warning(f"无法解析时间范围: {time_range}")
                                start_time = 0.0
                                end_time = 0.0

                        data["sentences"].append({
                            "idx": idx,
                            "text": text,
                            "start_time": start_time,
                            "end_time": end_time,
                        })

    # 加载 PPT
    ocr_path = Path(ocr_result_file)
    if ocr_path.exists():
        with open(ocr_path, "r", encoding="utf-8") as f:
            ocr_data = json.load(f)
            data["slides"] = ocr_data.get("slides", [])

    return data


def _align_with_ppt(sentence: dict, slides: list[dict]) -> dict | None:
    """
    时间对齐：找到句子对应的 PPT（参考 JS 的 alignWithPPT）
    
    Args:
        sentence: 句子数据
        slides: PPT 幻灯片列表
        
    Returns:
        匹配的 PPT 或 None
    """
    sentence_time = sentence.get("start_time", 0)

    # 找到时间上最近的 PPT（时间戳小于等于句子时间的最后一个）
    matched_slide = None
    for slide in reversed(slides):
        slide_time = slide.get("timestamp", 0)
        if slide_time <= sentence_time:
            matched_slide = slide
            break

    return matched_slide

async def _classify_sentence(
    sentence: dict,
    slide: dict | None,
    client: DashScopeClient,
) -> dict:
    """
    使用 AI 分类单个句子（参考 JS 的 classifySentence）
    """
    text = sentence.get("text", "")
    
    # 构建 PPT 上下文
    ppt_context = ""
    if slide and slide.get("structure"):
        structure = slide["structure"]
        ppt_context = f"""【对应PPT内容】
标题: {structure.get('title', '无')}
关键术语: {', '.join(structure.get('keyTerms', []))}
公式: {', '.join(structure.get('formulas', []))}"""
    else:
        ppt_context = "【无PPT内容】"

    prompt = f"""分析以下课程内容，判断其类型。

【语音内容】
{text}

{ppt_context}

分类标准：
- core: 核心知识点、定义、公式、定理、重要概念（PPT有对应内容时优先判断）
- explain: 对核心内容的解释、举例说明
- interact: 师生互动、提问、回答、点名、课堂讨论
- chat: 闲聊、跑题、与课程无关的内容（作业讨论、考试话题、个人轶事）
- transition: 纯过渡语、"那么"、"接下来"、"所以说"等无实质内容

返回 JSON: {{"reason": "简短理由", "label": "类型", "confidence": 0.0-1.0}}"""

    try:
        response = await client.generate_text(
            prompt=prompt,
            max_tokens=200,
            temperature=0.3,
        )

        # 解析 JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group(0))
            return {
                "label": result.get("label", "explain"),
                "confidence": result.get("confidence", 0.5),
                "reason": result.get("reason", ""),
            }

        return {"label": "explain", "confidence": 0.5, "reason": "解析失败"}

    except json.JSONDecodeError:
        return {"label": "explain", "confidence": 0.5, "reason": "JSON解析失败"}
    except Exception as e:
        return {"label": "explain", "confidence": 0.3, "reason": f"API错误: {str(e)}"}


async def _classify_batch(
    sentences: list[dict],
    slides: list[dict],
    words: list[dict],
    concurrency: int,
    task_id: str,
    output_path: Path,
) -> list[dict]:
    """
    批量分类（参考 JS 的 classifyBatch）
    """
    client = DashScopeClient(api_key=settings.dashscope_api_key)
    
    results = []
    semaphore = asyncio.Semaphore(concurrency)
    
    completed = 0
    start_time = asyncio.get_event_loop().time()
    
    # 限流：最小请求间隔
    last_request_time = 0
    min_interval = 0.1  # 100ms
    
    async def process_sentence(sentence: dict) -> dict:
        nonlocal completed, last_request_time
        
        async with semaphore:
            # 限流
            now = asyncio.get_event_loop().time()
            if now - last_request_time < min_interval:
                await asyncio.sleep(min_interval - (now - last_request_time))
            last_request_time = asyncio.get_event_loop().time()
            
            # 时间对齐
            slide = _align_with_ppt(sentence, slides)
            
            # AI 分类
            classification = await _classify_sentence(sentence, slide, client)
                
            
            # 构建结果
            result = {
                "idx": sentence.get("idx", 0),
                "text": sentence.get("text", ""),
                "startIdx": sentence.get("startIdx"),
                "endIdx": sentence.get("endIdx"),
                "start_time": sentence.get("start_time", 0),
                "end_time": sentence.get("end_time", 0),
                "label": classification["label"],
                "confidence": classification["confidence"],
                "reason": classification["reason"],
                "slideId": slide.get("frameId") if slide else None,
                "slideTitle": slide.get("structure", {}).get("title") if slide else None,
            }
            
            completed += 1
            
            # 进度日志
            if completed % 10 == 0:
                elapsed = asyncio.get_event_loop().time() - start_time
                speed = completed / elapsed if elapsed > 0 else 0
                remaining = (len(sentences) - completed) / speed if speed > 0 else 0
                logger.info(
                    f"📊 进度: {completed}/{len(sentences)} "
                    f"({completed/len(sentences)*100:.1f}%) - "
                    f"剩余: {remaining:.0f}秒"
                )
                
                # 更新进度
                progress = 0.45 + (completed / len(sentences)) * 0.1
                update_progress(
                    task_id,
                    ProgressStep.CONTENT_CLASSIFY,
                    progress,
                    f"正在分类: {completed}/{len(sentences)}",
                )
            
            return result
    
    # 并发执行
    tasks = [process_sentence(s) for s in sentences]
    results = await asyncio.gather(*tasks)
    
    # 按 idx 排序
    results = sorted(results, key=lambda x: x.get("idx", 0))
    
    # 保存中间结果
    segments_file = output_path / "segments.json"
    with open(segments_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    return results


def _save_empty_results(output_dir: str, task_id: str) -> dict[str, Any]:
    """保存空分类结果"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    empty_stats = {
        "core": 0,
        "explain": 0,
        "interact": 0,
        "chat": 0,
        "transition": 0,
    }

    classification_file = output_path / "classification.json"
    with open(classification_file, "w", encoding="utf-8") as f:
        json.dump({
            "segments": [],
            "statistics": empty_stats,
        }, f, ensure_ascii=False, indent=2)

    logger.info("内容分类完成: 视频无语音内容")

    update_progress(
        task_id,
        ProgressStep.CONTENT_CLASSIFY,
        0.55,
        "内容分类完成: 无语音内容",
    )

    return {
        "success": True,
        "classification_file": str(classification_file),
        "segment_count": 0,
        "statistics": empty_stats,
    }


def _finalize_results(
    results: list[dict],
    output_path: Path,
    task_id: str,
) -> dict[str, Any]:
    """最终化分类结果"""
    # 统计
    stats = {
        "core": 0,
        "explain": 0,
        "interact": 0,
        "chat": 0,
        "transition": 0,
    }

    total_duration = 0
    core_duration = 0

    for r in results:
        label = r.get("label", "unknown")
        if label in stats:
            stats[label] += 1
        
        duration = (r.get("end_time", 0) or 0) - (r.get("start_time", 0) or 0)
        if duration > 0:
            total_duration += duration
            if label == "core":
                core_duration += duration

    # 保存 classification.json（统一格式）
    classification_file = output_path / "classification.json"
    with open(classification_file, "w", encoding="utf-8") as f:
        json.dump({
            "segments": results,
            "statistics": stats,
        }, f, ensure_ascii=False, indent=2)

    # 保存 segments.json（兼容 JS 版本）
    segments_file = output_path / "segments.json"
    with open(segments_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 生成报告
    report = _generate_report(results, stats, total_duration, core_duration)
    report_file = output_path / "classification.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"\n✅ 分类完成！")
    logger.info(f"   总句子数: {len(results)}")
    logger.info(f"   统计: {stats}")
    logger.info(f"📁 输出: {classification_file}")

    update_progress(
        task_id,
        ProgressStep.CONTENT_CLASSIFY,
        0.55,
        f"内容分类完成: {len(results)} 个片段",
    )

    return {
        "success": True,
        "classification_file": str(classification_file),
        "segment_count": len(results),
        "statistics": stats,
    }


def _generate_report(
    results: list[dict],
    stats: dict,
    total_duration: float,
    core_duration: float,
) -> str:
    """
    生成统计报告（参考 JS 的 generateReport）
    """
    total = len(results) or 1  # 避免除零

    # 时间转换为分钟
    total_minutes = total_duration / 60000  # 假设时间单位是毫秒
    core_minutes = core_duration / 60000

    report = f"""# 内容分类统计

## 概览

| 类型 | 句子数 | 占比 | 说明 |
|------|--------|------|------|
| 核心知识 | {stats['core']} | {stats['core']/total*100:.1f}% | 必留 |
| 解释说明 | {stats['explain']} | {stats['explain']/total*100:.1f}% | 可选 |
| 课堂互动 | {stats['interact']} | {stats['interact']/total*100:.1f}% | 建议删 |
| 闲聊跑题 | {stats['chat']} | {stats['chat']/total*100:.1f}% | 必删 |
| 过渡语 | {stats['transition']} | {stats['transition']/total*100:.1f}% | 可删 |

## 时长分析

- 总时长: {total_minutes:.1f} 分钟
- 核心知识: {core_minutes:.1f} 分钟 ({core_duration/total_duration*100:.1f}% if total_duration > 0 else 0)

## 剪辑建议

**精要版**（仅保留核心知识）：
- 删除互动+闲聊+过渡语
- 可节省约 {total_minutes - core_minutes:.1f} 分钟

**完整版**（保留核心+解释）：
- 删除互动+闲聊
- 可节省约 {(stats['interact'] + stats['chat']) * 2 / 60:.1f} 分钟

## 详细分类

"""

    # 添加前20个分类示例
    for r in results[:20]:
        label = r.get("label", "unknown")
        text = r.get("text", "")[:50]
        reason = r.get("reason", "")
        report += f"- **{label}**: {text}...\n"
        if reason:
            report += f"  > 理由: {reason}\n"

    if len(results) > 20:
        report += f"\n... 共 {len(results)} 条记录\n"

    return report