"""
内容分类任务

使用 LLM 对语音转录内容进行分类，融合 PPT OCR 信息。
"""

import asyncio
import json
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


# 分类提示词模板
CLASSIFICATION_PROMPT = """你是一个课程内容分类助手。请根据以下规则对每个句子进行分类。

## 分类标签

1. **core** (核心知识) - 必须保留
   - 包含定义、公式、定理的句子
   - PPT 中出现的标题、关键词对应的讲解
   - 核心概念的详细解释

2. **explain** (解释说明) - 可选保留
   - 对核心知识的举例说明
   - 补充解释和推导过程

3. **interact** (课堂互动) - 建议删除
   - 提问、点名、课堂问答
   - 作业、考试相关讨论
   - "谁来说"、"举手"等互动语句

4. **chat** (闲聊跑题) - 必须删除
   - 纯语气词（"啊"、"嗯"、"呃"）
   - 与课程内容无关的闲聊
   - 跑题的对话

5. **transition** (过渡语) - 可以删除
   - "接下来"、"下面"等过渡语句
   - "我们继续"、"回到主题"等

## PPT 上下文

当前幻灯片内容：
{ppt_title}
{ppt_content}

请根据句子内容和 PPT 上下文进行分类。
"""


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
) -> dict[str, Any]:
    """
    对转录内容进行分类

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        sentences_file: 句子文件路径
        ocr_result_file: OCR 结果文件路径
        output_dir: 输出目录

    Returns:
        分类结果信息

    Raises:
        ClassificationError: 分类失败
    """
    logger.info("开始内容分类")

    update_progress(
        task_id,
        ProgressStep.CONTENT_CLASSIFY,
        0.45,
        "正在进行内容分类...",
    )

    try:
        # 读取句子
        sentences = _load_sentences(sentences_file)

        # 读取 OCR 结果
        ppt_slides = _load_ppt_slides(ocr_result_file)

        if not sentences:
            raise ClassificationError("没有找到可分类的句子")

        # 执行批量分类
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            classifications = loop.run_until_complete(
                _batch_classify(
                    sentences=sentences,
                    ppt_slides=ppt_slides,
                    task_id=task_id,
                )
            )
        finally:
            loop.close()

        # 统计各类型数量
        statistics = {label.value: 0 for label in ClassificationLabel}
        for cls in classifications:
            label = cls.get("label", "unknown")
            if label in statistics:
                statistics[label] += 1

        # 保存分类结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 保存 JSON
        classification_file = output_path / "classification.json"
        with open(classification_file, "w", encoding="utf-8") as f:
            json.dump({
                "segments": classifications,
                "statistics": statistics,
            }, f, ensure_ascii=False, indent=2)

        # 生成 Markdown 报告
        _generate_classification_report(
            classifications=classifications,
            statistics=statistics,
            output_path=output_path,
        )

        logger.info(f"内容分类完成: {len(classifications)} 个片段")

        update_progress(
            task_id,
            ProgressStep.CONTENT_CLASSIFY,
            0.55,
            f"内容分类完成: {len(classifications)} 个片段",
        )

        return {
            "success": True,
            "classification_file": str(classification_file),
            "segment_count": len(classifications),
            "statistics": statistics,
        }

    except Exception as e:
        logger.error(f"内容分类时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.CONTENT_CLASSIFY,
            0.0,
            f"内容分类失败: {str(e)}",
        )
        raise ClassificationError(f"内容分类失败: {e}")


def _load_sentences(sentences_file: str) -> list[dict]:
    """加载句子数据"""
    path = Path(sentences_file)

    if path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("sentences", [])
    elif path.suffix == ".txt":
        # 解析 sentences.txt 格式
        sentences = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 3:
                    sentences.append({
                        "idx": int(parts[0]),
                        "text": parts[2],
                    })
        return sentences
    else:
        raise ClassificationError(f"不支持的句子文件格式: {path.suffix}")


def _load_ppt_slides(ocr_result_file: str) -> list[dict]:
    """加载 PPT 数据"""
    with open(ocr_result_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("slides", [])


async def _batch_classify(
    sentences: list[dict],
    ppt_slides: list[dict],
    task_id: str,
    batch_size: int = 50,
) -> list[dict]:
    """批量分类句子"""
    client = DashScopeClient(api_key=settings.dashscope_api_key)

    # 为句子匹配 PPT 上下文
    sentences_with_ppt = _match_ppt_to_sentences(
        sentences,
        ppt_slides,
    )

    # 分批处理
    batches = [
        sentences_with_ppt[i:i + batch_size]
        for i in range(0, len(sentences_with_ppt), batch_size)
    ]

    all_classifications = []

    for batch_idx, batch in enumerate(batches):
        # 构建批量提示
        batch_prompts = []
        for item in batch:
            prompt = _build_classification_prompt(
                sentence_text=item["text"],
                ppt_title=item.get("ppt_title", ""),
                ppt_content=item.get("ppt_content", ""),
            )
            batch_prompts.append(prompt)

        # 批量调用 LLM
        batch_results = await client.classify_batch(
            sentences=[item["text"] for item in batch],
            ppt_context=[{
                "title": item.get("ppt_title", ""),
                "content": item.get("ppt_content", ""),
            } for item in batch],
            batch_size=batch_size,
        )

        all_classifications.extend(batch_results)

        # 更新进度
        progress = 0.45 + (batch_idx + 1) / len(batches) * 0.1
        update_progress(
            task_id,
            ProgressStep.CONTENT_CLASSIFY,
            progress,
            f"正在分类: {len(all_classifications)}/{len(sentences)}",
        )

    return all_classifications


def _match_ppt_to_sentences(
    sentences: list[dict],
    ppt_slides: list[dict],
) -> list[dict]:
    """为句子匹配对应的 PPT 内容"""
    result = []

    for sentence in sentences:
        # 如果句子有时间信息，尝试匹配对应时间的 PPT
        timestamp = sentence.get("start_time", sentence.get("timestamp", 0))

        # 找到时间最接近的 PPT
        matched_ppt = None
        min_diff = float("inf")

        for slide in ppt_slides:
            slide_time = slide.get("timestamp", 0)
            diff = abs(slide_time - timestamp)
            if diff < min_diff:
                min_diff = diff
                matched_ppt = slide

        # 匹配阈值：5秒内的 PPT
        if matched_ppt and min_diff <= 5:
            structure = matched_ppt.get("structure", {})
            result.append({
                **sentence,
                "ppt_title": structure.get("title", ""),
                "ppt_content": "\n".join(
                    structure.get("body", [])[:5]  # 只取前5行
                ),
            })
        else:
            result.append({
                **sentence,
                "ppt_title": "",
                "ppt_content": "",
            })

    return result


def _build_classification_prompt(
    sentence_text: str,
    ppt_title: str,
    ppt_content: str,
) -> str:
    """构建分类提示词"""
    ppt_section = ""
    if ppt_title or ppt_content:
        ppt_section = f"""
## PPT 上下文

标题: {ppt_title}

内容:
{ppt_content}
"""

    return f"""{CLASSIFICATION_PROMPT}
{ppt_section}

## 待分类句子

{sentence_text}

请只返回分类标签（core/explain/interact/chat/transition）和简短理由。
格式: 标签|理由
"""


def _generate_classification_report(
    classifications: list[dict],
    statistics: dict,
    output_path: Path,
):
    """生成分类 Markdown 报告"""
    report_lines = [
        "# 内容分类报告\n",
        "## 统计信息\n",
        f"- 总片段数: {len(classifications)}",
        f"- **core (核心)**: {statistics['core']} ({statistics['core']/len(classifications)*100:.1f}%)",
        f"- **explain (解释)**: {statistics['explain']} ({statistics['explain']/len(classifications)*100:.1f}%)",
        f"- **interact (互动)**: {statistics['interact']} ({statistics['interact']/len(classifications)*100:.1f}%)",
        f"- **chat (闲聊)**: {statistics['chat']} ({statistics['chat']/len(classifications)*100:.1f}%)",
        f"- **transition (过渡)**: {statistics['transition']} ({statistics['transition']/len(classifications)*100:.1f}%)",
        "\n## 详细分类\n",
    ]

    for cls in classifications:
        label = cls.get("label", "unknown")
        text = cls.get("text", "")[:100]  # 截断长文本
        reason = cls.get("reason", "")

        report_lines.append(f"- **{label}**: {text}...")
        if reason:
            report_lines.append(f"  理由: {reason}")

    report_file = output_path / "classification.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
