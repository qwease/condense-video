"""
TTS 语音合成任务

使用 Edge TTS（免费）或 DashScope CosyVoice 生成配音。

功能:
1. 使用 Edge TTS（免费）或百炼 CosyVoice 生成配音
2. 长文本分段处理（处理超长句子）
3. 按章节生成，合并音频文件
4. 计算音频时长
5. 断点续传支持
6. 并发处理
"""

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from datetime import datetime

from celery import shared_task
from core.config import settings
from core.exceptions import VideoProcessingException
from core.logging import setup_logging
from core.progress import ProgressStep
from services.redis_client import update_progress

logger = setup_logging()


class TTSError(VideoProcessingException):
    """TTS 生成错误"""
    pass


# 默认配置
DEFAULT_CONFIG = {
    "model": settings.dashscope_tts_model,           # DashScope TTS 模型
    "voice": settings.tts_voice,                     # DashScope TTS 音色
    "edge_voice": settings.edgetts_voice,  # Edge TTS 中文女声
    "concurrency": settings.tts_concurrency,                      # 并发数
    "max_length": settings.tts_max_length,                     # TTS 单次最大字符数
    "rate": settings.edgetts_rate,                        # Edge TTS 语速
    "pitch": "+5Hz",                       # Edge TTS 语调
    "speech_rate": 1.2,                    # DashScope 语速
    "pitch_rate": 1.1,                     # DashScope 语调
}


def _run_async(coro):
    """安全地运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


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
    engine: str = "edgetts",
    voice: str | None = None,
    model: str | None = None,
    resume: bool = True,
    **kwargs,
) -> dict[str, Any]:
    """
    生成 TTS 配音

    Args:
        self: Celery 任务绑定
        task_id: 任务 ID
        condensed_file: 浓缩文本文件 (condensed.json 或 condensed_for_tts.txt)
        output_dir: 输出目录
        engine: TTS 引擎 (edgetts, dashscope)
        voice: 音色名称
        model: 模型名称 (DashScope)
        resume: 是否支持断点续传
        **kwargs: 额外配置参数

    Returns:
        TTS 生成结果

    Raises:
        TTSError: TTS 生成失败
    """
    # 合并配置
    config = DEFAULT_CONFIG.copy()
    config.update(kwargs)
    
    # 设置音色
    if voice:
        if engine == "edgetts":
            config["edge_voice"] = voice
        else:
            config["voice"] = voice
    
    if model:
        config["model"] = model

    use_edge_tts = engine == "edgetts"
    
    logger.info(f"🎙️ 开始生成 TTS")
    logger.info(f"🔊 TTS 引擎: {'Edge TTS (免费)' if use_edge_tts else 'DashScope'}")
    logger.info(f"⚙️ 配置: {json.dumps(config, ensure_ascii=False)}")

    update_progress(
        task_id,
        ProgressStep.TTS_GENERATE,
        0.8,
        f"正在生成 TTS 配音 ({engine})...",
    )

    try:
        # 准备输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 加载浓缩文稿
        scripts = _load_scripts(condensed_file)
        
        if not scripts:
            raise TTSError("没有找到可生成配音的文稿")

        logger.info(f"📝 加载 {len(scripts)} 个文稿")

        # 检查断点续传
        timing_file = output_path / "audio_timing.json"
        timing = {"segments": []}
        processed_ids = set()

        if resume and timing_file.exists():
            with open(timing_file, "r", encoding="utf-8") as f:
                timing = json.load(f)
            processed_ids = {s["chapterId"] for s in timing.get("segments", [])}
            logger.info(f"📂 已加载 {len(processed_ids)} 个已完成的音频")

        # 待处理文稿
        pending = [s for s in scripts if s.get("chapterId") not in processed_ids]
        logger.info(f"📊 待处理: {len(pending)} 个文稿")

        if not pending:
            logger.info("✅ 所有音频已生成完成")
            return _finalize_tts(timing, output_path, task_id, engine, config)

        # 生成配音
        _run_async(
            _generate_all_chapters(
                scripts=pending,
                output_dir=output_path,
                config=config,
                use_edge_tts=use_edge_tts,
                timing=timing,
                timing_file=timing_file,
                task_id=task_id,
            )
        )

        return _finalize_tts(timing, output_path, task_id, engine, config)

    except Exception as e:
        import traceback
        logger.error(f"TTS 生成失败: {e}\n{traceback.format_exc()}")
        update_progress(
            task_id,
            ProgressStep.TTS_GENERATE,
            0.0,
            f"TTS 生成失败: {str(e)}",
        )
        raise TTSError(f"TTS 生成失败: {e}")


def _load_scripts(condensed_file: str) -> list[dict]:
    """
    加载浓缩文稿
    
    支持两种格式：
    1. condensed.json - 章节化文稿
    2. condensed_for_tts.txt - 纯文本
    """
    file_path = Path(condensed_file)
    
    if not file_path.exists():
        # 尝试其他文件名
        alt_paths = [
            file_path.parent / "condensed.json",
            file_path.parent / "condensed_for_tts.txt",
        ]
        for alt in alt_paths:
            if alt.exists():
                file_path = alt
                break
    
    if not file_path.exists():
        raise TTSError(f"找不到浓缩文稿文件: {condensed_file}")

    if file_path.suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            scripts = data.get("scripts", [])
            if scripts:
                return scripts
            # 降级：如果没有 scripts，创建单个章节
            return [{
                "chapterId": 1,
                "title": "课程内容",
                "script": data.get("text", ""),
            }]
    else:
        # 纯文本文件
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        return [{
            "chapterId": 1,
            "title": "课程内容",
            "script": text,
        }]


def _split_text_for_tts(text: str, max_length: int = 250) -> list[str]:
    """
    分段文本用于 TTS（处理超长句子）
    
    参考 JS 版本的 splitTextForTTS
    """
    chunks = []

    # 按句子分割
    sentences = re.findall(r'[^。！？.!?]+[。！？.!?]+', text)
    if not sentences:
        sentences = [text]

    current = ""

    for sentence in sentences:
        # 如果单个句子本身超过 max_length，强制按字符分割
        if len(sentence) > max_length:
            # 先保存当前累积的内容
            if current:
                chunks.append(current.strip())
                current = ""
            # 强制分割长句
            for i in range(0, len(sentence), max_length):
                chunks.append(sentence[i:i + max_length])
        elif len(current) + len(sentence) > max_length:
            chunks.append(current.strip())
            current = sentence
        else:
            current += sentence

    if current.strip():
        chunks.append(current.strip())

    # 二次检查：确保没有段落超限
    safe_chunks = []
    for chunk in chunks:
        if len(chunk) > max_length:
            for i in range(0, len(chunk), max_length):
                safe_chunks.append(chunk[i:i + max_length])
        else:
            safe_chunks.append(chunk)

    return safe_chunks


async def _generate_all_chapters(
    scripts: list[dict],
    output_dir: Path,
    config: dict,
    use_edge_tts: bool,
    timing: dict,
    timing_file: Path,
    task_id: str,
):
    """生成所有章节的配音"""
    semaphore = asyncio.Semaphore(config["concurrency"])
    
    logger.info(f"⚡ 并发数: {config['concurrency']}")

    async def process_chapter(script: dict, index: int):
        async with semaphore:
            logger.info(
                f"\n🎙️ [{index + 1}/{len(scripts)}] 章节 {script['chapterId']}: "
                f"{script['title'][:30]}..."
            )

            audio_path = await _generate_chapter_audio(
                script=script,
                output_dir=output_dir,
                config=config,
                use_edge_tts=use_edge_tts,
            )

            if audio_path and Path(audio_path).exists():
                duration = _get_audio_duration(audio_path)
                logger.info(
                    f"   ✅ [{index + 1}/{len(scripts)}] 完成: "
                    f"{duration / 60:.2f} 分钟"
                )

                segment = {
                    "chapterId": script["chapterId"],
                    "title": script["title"],
                    "audioPath": audio_path,
                    "duration": duration,
                    "textLength": len(script.get("script", "")),
                }
            else:
                logger.warning(f"   ❌ [{index + 1}/{len(scripts)}] 失败")
                segment = {
                    "chapterId": script["chapterId"],
                    "title": script["title"],
                    "audioPath": None,
                    "duration": 0,
                    "error": "生成失败",
                }

            # 保存进度
            timing["segments"].append(segment)
            _save_timing(timing, timing_file, config, use_edge_tts)

            # 更新进度
            progress = 0.8 + ((index + 1) / len(scripts)) * 0.05
            update_progress(
                task_id,
                ProgressStep.TTS_GENERATE,
                progress,
                f"正在生成 TTS: {index + 1}/{len(scripts)}",
            )

            # 按章节排序
            timing["segments"].sort(key=lambda x: x["chapterId"])
            return segment

    # 并发处理
    tasks = [process_chapter(script, i) for i, script in enumerate(scripts)]
    await asyncio.gather(*tasks)


async def _generate_chapter_audio(
    script: dict,
    output_dir: Path,
    config: dict,
    use_edge_tts: bool,
) -> str | None:
    """
    生成单章配音
    
    返回合并后的音频文件路径
    """
    chapter_id = script.get("chapterId", 1)
    chapter_dir = output_dir / f"chapter_{chapter_id}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    # 分段文本
    text = script.get("script", "")
    if not text.strip():
        logger.warning(f"章节 {chapter_id} 文本为空")
        return None

    chunks = _split_text_for_tts(text, config["max_length"])
    logger.info(f"   📝 分 {len(chunks)} 段处理")

    segment_files = []
    audio_format = "mp3"

    for i, chunk in enumerate(chunks):
        segment_path = chapter_dir / f"segment_{i}.{audio_format}"

        # 断点续传：跳过已存在的
        if segment_path.exists() and segment_path.stat().st_size > 100:
            logger.info(f"   ⏭️ 跳过已存在: segment_{i}")
            segment_files.append(str(segment_path))
            continue

        logger.info(f"   🎙️ 生成 segment_{i + 1}/{len(chunks)} ({len(chunk)}字)...")

        success = False

        if use_edge_tts:
            success = await _edge_tts_synthesize(
                text=chunk,
                output_path=str(segment_path),
                voice=config["edge_voice"],
                rate=config["rate"],
                pitch=config["pitch"],
            )
        else:
            success = await _dashscope_tts_synthesize(
                text=chunk,
                output_path=str(segment_path),
                voice=config["voice"],
                model=config["model"],
            )

        if success:
            segment_files.append(str(segment_path))

        # 延迟避免限流
        await asyncio.sleep(0.3)

    # 合并音频
    if not segment_files:
        return None

    final_path = output_dir / f"chapter_{chapter_id}.{audio_format}"
    success = _merge_audio_files(segment_files, str(final_path))

    if success:
        # 清理分段文件
        await asyncio.sleep(0.5)
        shutil.rmtree(chapter_dir, ignore_errors=True)
        return str(final_path)

    return None


async def _edge_tts_synthesize(
    text: str,
    output_path: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+20%",
    pitch: str = "+5Hz",
) -> bool:
    """使用 Edge TTS 合成音频"""
    try:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        await communicate.save(output_path)

        # 验证文件
        if Path(output_path).exists() and Path(output_path).stat().st_size > 100:
            return True
        else:
            logger.warning(f"Edge TTS 生成的文件过小或不存在")
            return False

    except ImportError:
        logger.error("edge-tts 未安装，请运行: pip install edge-tts")
        return False
    except Exception as e:
        logger.error(f"Edge TTS 失败: {e}")
        return False


async def _dashscope_tts_synthesize(
    text: str,
    output_path: str,
    voice: str = "Cherry",
    model: str = "qwen3-tts-flash",
) -> bool:
    """使用 DashScope TTS 合成音频"""
    try:
        from services.dashscope import DashScopeClient

        client = DashScopeClient(api_key=settings.dashscope_api_key)
        audio_data = await client.tts(text=text, voice=voice, model=model)

        if audio_data and len(audio_data) > 100:
            with open(output_path, "wb") as f:
                f.write(audio_data)
            return True
        else:
            logger.warning(f"DashScope TTS 返回的音频数据过小")
            return False

    except Exception as e:
        import traceback
        logger.error(f"DashScope TTS 失败: {e}\n{traceback.format_exc()}")
        return False


def _merge_audio_files(audio_files: list[str], output_path: str) -> bool:
    """使用 FFmpeg 合并音频文件"""
    if not audio_files:
        return False

    if len(audio_files) == 1:
        shutil.copy(audio_files[0], output_path)
        return True

    # 生成 concat 文件
    concat_path = output_path + ".txt"
    concat_content = "\n".join(
        f"file '{Path(f).resolve().as_posix()}'"
        for f in audio_files
    )

    try:
        with open(concat_path, "w", encoding="utf-8") as f:
            f.write(concat_content)

        # 使用 FFmpeg 合并
        # 注意：不使用 -c copy，而是重新编码，避免格式不兼容问题
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_path,
            "-acodec", "libmp3lame",  # 重新编码为 MP3
            "-q:a", "2",              # 高质量
            output_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,  # 重新编码需要更长时间
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg 合并失败: {stderr[-500:]}")  # 只显示最后500字符
            
            # 尝试备用方案：使用 pydub
            return _merge_audio_files_pydub(audio_files, output_path)

        return True

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg 合并超时，尝试使用 pydub")
        return _merge_audio_files_pydub(audio_files, output_path)
    except Exception as e:
        logger.error(f"合并音频失败: {e}，尝试使用 pydub")
        return _merge_audio_files_pydub(audio_files, output_path)
    finally:
        # 清理 concat 文件
        try:
            Path(concat_path).unlink(missing_ok=True)
        except:
            pass


def _merge_audio_files_pydub(audio_files: list[str], output_path: str) -> bool:
    """使用 pydub 合并音频文件（备用方案）"""
    try:
        from pydub import AudioSegment

        logger.info(f"使用 pydub 合并 {len(audio_files)} 个音频文件...")

        combined = AudioSegment.empty()

        for i, audio_file in enumerate(audio_files):
            try:
                # 自动检测格式
                if audio_file.endswith(".wav"):
                    audio = AudioSegment.from_wav(audio_file)
                elif audio_file.endswith(".mp3"):
                    audio = AudioSegment.from_mp3(audio_file)
                else:
                    audio = AudioSegment.from_file(audio_file)
                
                combined += audio
                logger.debug(f"已合并: {audio_file}")
            except Exception as e:
                logger.warning(f"无法加载音频 {audio_file}: {e}")
                # 添加 1 秒静音作为占位
                combined += AudioSegment.silent(duration=1000)

        # 导出为 MP3
        combined.export(output_path, format="mp3", bitrate="128k")
        logger.info(f"pydub 合并完成: {output_path}")
        return True

    except ImportError:
        logger.error("pydub 未安装，请运行: pip install pydub")
        return False
    except Exception as e:
        logger.error(f"pydub 合并失败: {e}")
        return False


def _get_audio_duration(audio_path: str) -> float:
    """使用 ffprobe 获取音频时长"""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path,
        ]

        # 不使用 text=True，避免 Windows GBK 编码问题
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )

        if result.returncode == 0:
            # 手动解码
            stdout = result.stdout.decode("utf-8", errors="ignore").strip()
            if stdout:
                return float(stdout)

    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe 超时: {audio_path}")
    except ValueError as e:
        logger.warning(f"无法解析音频时长: {e}")
    except Exception as e:
        logger.warning(f"无法获取音频时长: {e}")

    return 0.0


def _save_timing(
    timing: dict,
    timing_file: Path,
    config: dict,
    use_edge_tts: bool,
):
    """保存进度"""
    total_duration = sum(s.get("duration", 0) for s in timing.get("segments", []))

    data = {
        "generatedAt": datetime.now().isoformat(),
        "voiceModel": "edge-tts" if use_edge_tts else "cosyvoice-v1",
        "voiceId": config["edge_voice"] if use_edge_tts else config["voice"],
        "totalDuration": total_duration,
        "segments": timing["segments"],
    }

    with open(timing_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _finalize_tts(
    timing: dict,
    output_path: Path,
    task_id: str,
    engine: str,
    config: dict,
) -> dict[str, Any]:
    """完成 TTS 生成，合并所有章节音频"""
    segments = timing.get("segments", [])
    
    # 统计
    success_count = len([s for s in segments if s.get("audioPath")])
    fail_count = len([s for s in segments if not s.get("audioPath")])
    total_duration = sum(s.get("duration", 0) for s in segments)

    logger.info(f"\n✅ TTS 完成！")
    logger.info(f"   成功: {success_count} 个")
    logger.info(f"   失败: {fail_count} 个")
    logger.info(f"   总时长: {total_duration / 60:.2f} 分钟")

    # 合并所有章节为一个文件
    chapter_files = [
        s["audioPath"] for s in segments
        if s.get("audioPath") and Path(s["audioPath"]).exists()
    ]

    merged_file = output_path / "tts_audio.mp3"
    if chapter_files:
        _merge_audio_files(chapter_files, str(merged_file))
        logger.info(f"📁 合并输出: {merged_file}")

    update_progress(
        task_id,
        ProgressStep.TTS_GENERATE,
        0.85,
        f"TTS 生成完成: {success_count} 个章节",
    )

    return {
        "success": True,
        "audio_file": str(merged_file) if merged_file.exists() else None,
        "timing_file": str(output_path / "audio_timing.json"),
        "segment_count": success_count,
        "total_duration": total_duration,
        "engine": engine,
        "voice": config["edge_voice"] if engine == "edgetts" else config["voice"],
    }