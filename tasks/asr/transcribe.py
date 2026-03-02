"""
ASR 转录任务

使用 DashScope paraformer-v2 模型进行语音识别。
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


def _run_async(coro):
    """
    安全地运行异步函数

    检测是否有运行中的事件循环，如果有则使用 nest_asyncio
    """
    try:
        asyncio.get_running_loop()
        # 已经有事件循环在运行，应用 nest_asyncio
        import nest_asyncio
        nest_asyncio.apply()
    except RuntimeError:
        pass  # 没有运行中的事件循环

    return asyncio.run(coro)


class ASRTranscriptError(VideoProcessingException):
    """ASR 转录错误"""
    pass


@shared_task(
    name="tasks.asr.transcribe",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def transcribe_audio(
    self,
    task_id: str,
    audio_url: str,
    output_dir: str,
    language: str = "zh",
) -> dict[str, Any]:
    """
    转录音频文件

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        audio_url: 音频文件 URL (公网可访问)
        output_dir: 输出目录
        language: 语言代码 (默认 zh)

    Returns:
        转录结果信息

    Raises:
        ASRTranscriptError: 转录失败
    """
    logger.info(f"开始 ASR 转录: {audio_url}")

    update_progress(
        task_id,
        ProgressStep.ASR_TRANSCRIBE,
        0.15,
        "正在转录音频...",
    )

    try:
        # 创建 DashScope 客户端
        client = DashScopeClient(
            api_key=settings.dashscope_api_key,
        )

        # 调用 ASR API (异步模式 + 轮询)
        # 使用 _run_async 安全地处理异步调用（兼容已存在事件循环的情况）
        result = _run_async(client.transcribe(
            audio_url=audio_url,
            language=language,
            max_wait=600000,  # 10 分钟超时
        ))

        # 保存转录结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        transcript_file = output_path / "transcript.json"
        with open(transcript_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 统计信息 - 转换后的格式使用 "utterances" 键
        utterances = result.get("utterances", [])
        total_duration = 0
        word_count = 0

        for utt in utterances:
            total_duration += (utt.get("end_time", 0) - utt.get("begin_time", 0)) / 1000
            word_count += len(utt.get("text", ""))

        logger.info(
            f"ASR 转录完成: {len(utterances)} 个语音片段, "
            f"{total_duration:.1f}秒, {word_count} 字"
        )

        update_progress(
            task_id,
            ProgressStep.ASR_TRANSCRIBE,
            0.25,
            f"转录完成: {len(utterances)} 个片段, {word_count} 字",
        )

        return {
            "success": True,
            "transcript_path": str(transcript_file),
            "utterance_count": len(utterances),
            "total_duration": total_duration,
            "word_count": word_count,
            "language": language,
            "result": result,
        }

    except Exception as e:
        logger.error(f"ASR 转录时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.ASR_TRANSCRIBE,
            0.0,
            f"转录失败: {str(e)}",
        )
        raise ASRTranscriptError(f"ASR 转录失败: {e}")


@shared_task(
    name="tasks.asr.convert_transcript",
    bind=True,
)
def convert_transcript(
    self,
    task_id: str,
    transcript_file: str,
    output_dir: str,
) -> dict[str, Any]:
    """
    转换转录结果格式

    将 DashScope ASR 原始输出转换为标准格式，并执行智能分句。

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        transcript_file: 转录文件路径
        output_dir: 输出目录

    Returns:
        转换结果信息
    """
    logger.info(f"转换转录结果: {transcript_file}")

    try:
        # 读取原始转录 - 转换后的格式使用 "utterances" 键
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)

        utterances = transcript_data.get("utterances", [])

        # 构建字级别列表
        words = []
        for utt in utterances:
            utt_words = utt.get("words", [])
            for word in utt_words:
                words.append({
                    "text": word.get("text", ""),
                    "start_time": word.get("begin_time", 0) / 1000,  # 转为秒
                    "end_time": word.get("end_time", 0) / 1000,
                    "gap": 0.0,  # 稍后计算
                })

        # 计算静音间隔
        for i in range(len(words) - 1):
            words[i]["gap"] = words[i + 1]["start_time"] - words[i]["end_time"]

        # 智能分句
        sentences = []
        current_words = []
        last_end_time = 0

        for word in words:
            current_words.append(word)

            # 检查是否应该分句
            should_split = False
            text = word["text"]

            # 条件1: 句子结束标点
            if text and text[-1] in "。！？.!?!":
                should_split = True

            # 条件2: 长静音
            elif word["gap"] >= 0.5 and len(current_words) > 1:
                should_split = True

            if should_split:
                # 形成句子
                sentence_text = "".join(w["text"] for w in current_words)
                start_time = current_words[0]["start_time"]
                end_time = current_words[-1]["end_time"]

                sentences.append({
                    "idx": len(sentences),
                    "text": sentence_text,
                    "start_idx": words.index(current_words[0]),
                    "end_idx": words.index(current_words[-1]),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": end_time - start_time,
                    "words": current_words.copy(),
                })

                current_words = []

        # 处理剩余
        if current_words:
            sentence_text = "".join(w["text"] for w in current_words)
            start_time = current_words[0]["start_time"]
            end_time = current_words[-1]["end_time"]

            sentences.append({
                "idx": len(sentences),
                "text": sentence_text,
                "start_idx": words.index(current_words[0]),
                "end_idx": words.index(current_words[-1]),
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "words": current_words.copy(),
            })

        # 保存转换结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 保存 subtitles_words.json
        subtitles_file = output_path / "subtitles_words.json"
        with open(subtitles_file, "w", encoding="utf-8") as f:
            json.dump({"words": words}, f, ensure_ascii=False, indent=2)

        # 保存 sentences.txt (格式: idx|start_time-end_time|text)
        sentences_file = output_path / "sentences.txt"
        with open(sentences_file, "w", encoding="utf-8") as f:
            for sent in sentences:
                # 使用实际时间（秒），保留3位小数
                start_ts = f"{sent['start_time']:.3f}"
                end_ts = f"{sent['end_time']:.3f}"
                f.write(f'{sent["idx"]}|{start_ts}-{end_ts}|{sent["text"]}\n')

        # 保存 transcript_converted.json
        converted_file = output_path / "transcript_converted.json"
        with open(converted_file, "w", encoding="utf-8") as f:
            json.dump({
                "subtitles_words": words,
                "sentences": sentences,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"转录结果转换完成: {len(sentences)} 个句子")

        return {
            "success": True,
            "subtitles_file": str(subtitles_file),
            "sentences_file": str(sentences_file),
            "converted_file": str(converted_file),
            "sentence_count": len(sentences),
            "word_count": len(words),
        }

    except Exception as e:
        logger.error(f"转换转录结果时发生错误: {e}")
        raise ASRTranscriptError(f"转换转录结果失败: {e}")
