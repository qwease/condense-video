"""
TTS 语音合成任务

使用 DashScope CosyVoice 或 Edge TTS 生成配音。
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
from utils.text import truncate_for_tts

logger = setup_logging()


class TTSError(VideoProcessingException):
    """TTS 生成错误"""
    pass


@shared_task(
    name="tasks.tts.generate",
    bind=True,
    max_retries=2,
)
def generate_tts(
    self,
    task_id: str,
    condensed_file: str,
    output_dir: str,
    engine: str = "dashscope",
    voice: str = "Cherry",
    model: str = "qwen3-tts-flash",
) -> dict[str, Any]:
    """
    生成 TTS 配音

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        condensed_file: 浓缩文本文件
        output_dir: 输出目录
        engine: TTS 引擎 (dashscope, edgetts)
        voice: 音色名称
        model: 模型名称 (DashScope)

    Returns:
        TTS 生成结果

    Raises:
        TTSError: TTS 生成失败
    """
    logger.info(f"开始生成 TTS: engine={engine}, voice={voice}")

    update_progress(
        task_id,
        ProgressStep.TTS_GENERATE,
        0.8,
        f"正在生成 TTS 配音 ({engine})...",
    )

    try:
        # 读取浓缩文本
        with open(condensed_file, "r", encoding="utf-8") as f:
            text = f.read()

        if not text:
            raise TTSError("浓缩文本为空")

        # 截断为适合 TTS 的片段
        if engine == "dashscope":
            max_length = 600  # DashScope 限制 600 字/段
        else:
            max_length = 1000  # Edge TTS 限制较宽松

        segments = truncate_for_tts(
            text=text,
            max_length=max_length,
            split_at_sentence=True,
        )

        # 生成 TTS
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            audio_files = loop.run_until_complete(
                _generate_tts_audio(
                    segments=segments,
                    output_dir=output_dir,
                    engine=engine,
                    voice=voice,
                    model=model,
                    task_id=task_id,
                )
            )
        finally:
            loop.close()

        # 合并音频文件
        output_path = Path(output_dir)
        merged_file = output_path / "tts_audio.mp3"

        _merge_audio_files(audio_files, str(merged_file))

        # 生成时间信息
        timing_info = _create_timing_info(
            segments=segments,
            audio_files=audio_files,
        )

        timing_file = output_path / "audio_timing.json"
        with open(timing_file, "w", encoding="utf-8") as f:
            json.dump(timing_info, f, ensure_ascii=False, indent=2)

        logger.info(f"TTS 生成完成: {len(segments)} 个片段")

        update_progress(
            task_id,
            ProgressStep.TTS_GENERATE,
            0.85,
            f"TTS 生成完成: {len(segments)} 个片段",
        )

        return {
            "success": True,
            "audio_file": str(merged_file),
            "timing_file": str(timing_file),
            "segment_count": len(segments),
            "total_duration": timing_info.get("total_duration", 0),
            "engine": engine,
            "voice": voice,
        }

    except Exception as e:
        logger.error(f"TTS 生成时发生错误: {e}")
        update_progress(
            task_id,
            ProgressStep.TTS_GENERATE,
            0.0,
            f"TTS 生成失败: {str(e)}",
        )
        raise TTSError(f"TTS 生成失败: {e}")


async def _generate_tts_audio(
    segments: list[str],
    output_dir: str,
    engine: str,
    voice: str,
    model: str,
    task_id: str,
    concurrency: int = 3,
) -> list[str]:
    """生成 TTS 音频文件"""
    client = DashScopeClient(api_key=settings.dashscope_api_key)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if engine == "dashscope":
        # 使用 DashScope CosyVoice
        audio_files = await client.tts_batch(
            texts=segments,
            voice=voice,
            model=model,
            output_dir=str(output_path),
            concurrency=concurrency,
        )
    else:
        # 使用 Edge TTS
        audio_files = await _generate_edge_tts(
            segments=segments,
            voice=voice,
            output_dir=output_path,
            task_id=task_id,
        )

    return audio_files


async def _generate_edge_tts(
    segments: list[str],
    voice: str,
    output_dir: Path,
    task_id: str,
) -> list[str]:
    """使用 Edge TTS 生成音频"""
    import edge_tts

    audio_files = []

    for i, text in enumerate(segments):
        output_file = output_path / f"segment_{i:05d}.mp3"

        try:
            await edge_tts.Communicate(
                text=text,
                voice=voice,
            ).save(str(output_file))

            audio_files.append(str(output_file))

            # 更新进度
            progress = 0.8 + (i + 1) / len(segments) * 0.05
            update_progress(
                task_id,
                ProgressStep.TTS_GENERATE,
                progress,
                f"正在生成 TTS: {i + 1}/{len(segments)}",
            )

        except Exception as e:
            logger.warning(f"Edge TTS 片段 {i} 生成失败: {e}")
            # 创建静音占位文件
            _create_silent_audio(str(output_file), duration=1.0)
            audio_files.append(str(output_file))

    return audio_files


def _create_silent_audio(file_path: str, duration: float = 1.0):
    """创建静音音频文件"""
    from pydub import AudioSegment

    silence = AudioSegment.silent(duration=int(duration * 1000))
    silence.export(file_path, format="mp3")


def _merge_audio_files(audio_files: list[str], output_file: str):
    """合并多个音频文件"""
    from pydub import AudioSegment

    if not audio_files:
        return

    combined = AudioSegment.empty()

    for audio_file in audio_files:
        try:
            audio = AudioSegment.from_mp3(audio_file)
            combined += audio
        except Exception as e:
            logger.warning(f"无法加载音频文件 {audio_file}: {e}")

    combined.export(output_file, format="mp3")


def _create_timing_info(
    segments: list[str],
    audio_files: list[str],
) -> dict:
    """创建音频时间信息"""
    from pydub import AudioSegment

    timing_segments = []
    current_time = 0.0

    for i, (text, audio_file) in enumerate(zip(segments, audio_files)):
        try:
            audio = AudioSegment.from_mp3(audio_file)
            duration = len(audio) / 1000.0  # 转为秒

            timing_segments.append({
                "index": i,
                "text": text,
                "audio_file": Path(audio_file).name,
                "duration": duration,
                "start_time": current_time,
                "end_time": current_time + duration,
            })

            current_time += duration

        except Exception as e:
            logger.warning(f"无法获取音频时长 {audio_file}: {e}")
            # 使用文本长度估算
            estimated_duration = len(text) * 0.15

            timing_segments.append({
                "index": i,
                "text": text,
                "audio_file": Path(audio_file).name,
                "duration": estimated_duration,
                "start_time": current_time,
                "end_time": current_time + estimated_duration,
            })

            current_time += estimated_duration

    return {
        "segments": timing_segments,
        "total_duration": current_time,
    }
