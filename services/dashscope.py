"""
DashScope API 客户端

提供阿里云 DashScope API 的统一接口：
- ASR 语音识别 (paraformer-v2)
- OCR 图像识别 (qwen-vl-plus)
- LLM 文本生成 (qwen-plus)
- TTS 语音合成 (qwen3-tts-flash)
"""

import asyncio
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

import json
import re
import logging
import httpx
from pathlib import Path
import base64
import mimetypes

from core.config import settings
from core.exceptions import ASRException, LLMException, OCRException, TTSException


# DashScope API 基础 URL
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"


class DashScopeClient:
    """
    DashScope API 客户端

    提供 ASR、OCR、LLM、TTS 等服务的统一调用接口。
    支持自动重试和错误处理。
    """

    def __init__(self, api_key: str | None = None):
        """
        初始化客户端

        Args:
            api_key: DashScope API Key，默认从配置读取
        """
        self.api_key = api_key or settings.dashscope_api_key
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY is required")

    def _get_headers(self, extra_headers: dict | None = None) -> dict[str, str]:
        """获取请求头"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        处理 HTTP 响应

        Args:
            response: HTTP 响应对象

        Returns:
            解析后的 JSON 响应

        Raises:
            ASRException: ASR 相关错误
            LLMException: LLM 相关错误
            TTSException: TTS 相关错误
            OCRException: OCR 相关错误
        """
        if response.status_code == 200:
            return response.json()

        error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = error_data.get("message", error_data.get("error", response.text))
        raise Exception(f"HTTP {response.status_code}: {error_msg}")

    # ==================== ASR 语音识别 ====================

    async def transcribe(
        self,
        audio_url: str,
        language: str = "zh",
        max_wait: int = 600000,
    ) -> dict[str, Any]:
        """
        ASR 语音识别 (异步模式)

        Args:
            audio_url: 音频文件 URL (需要公网可访问)
            language: 语言代码，默认 zh
            max_wait: 最大等待时间 (毫秒)

        Returns:
            转录结果，格式兼容火山引擎
        """
        # 提交 ASR 任务
        body = {
            "model": settings.dashscope_asr_model,
            "input": {
                "file_urls": [audio_url],
            },
            "parameters": {
                "language": language,
                "punctuation": True,
                "disfluency_removal": True,
                "word_timestamp": True,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{DASHSCOPE_BASE}/api/v1/services/audio/asr/transcription",
                headers=self._get_headers({"X-DashScope-Async": "enable"}),
                json=body,
            )

            result = response.json()

            if response.status_code != 200:
                raise ASRException(f"ASR task submission failed: {result}")

            task_id = result.get("output", {}).get("task_id")
            if not task_id:
                raise ASRException(f"No task_id in response: {result}")

            return await self._poll_asr_result(task_id, max_wait)

    async def _poll_asr_result(self, task_id: str, max_wait: int) -> dict[str, Any]:
        """
        轮询 ASR 任务结果

        Args:
            task_id: 任务 ID
            max_wait: 最大等待时间 (毫秒)

        Returns:
            转录结果
        """
        

        logger = logging.getLogger(__name__)
        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            while (time.time() - start_time) * 1000 < max_wait:
                await asyncio.sleep(3)

                response = await client.get(
                    f"{DASHSCOPE_BASE}/api/v1/tasks/{task_id}",
                    headers=self._get_headers(),
                )

                result = response.json()

                if response.status_code != 200:
                    raise ASRException(f"Failed to poll ASR result: {result}")

                output = result.get("output", {})
                status = output.get("task_status")

                if status == "SUCCEEDED":
                    # 保存原始响应以便调试
                    debug_dir = Path("data/debug/asr")
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    debug_file = debug_dir / f"{task_id}_raw.json"
                    with open(debug_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                    logger.info(f"ASR task {task_id} succeeded, output keys: {list(output.keys())}")
                    logger.info(f"results: {output.get('results', 'N/A')}")
                    logger.info(f"transcripts: {output.get('transcripts', 'N/A')}")

                    converted = self._convert_asr_result(output)
                    # 同时保存转换后的结果
                    converted_file = debug_dir / f"{task_id}_converted.json"
                    with open(converted_file, "w", encoding="utf-8") as f:
                        json.dump(converted, f, ensure_ascii=False, indent=2)

                    return converted
                elif status == "FAILED":
                    raise ASRException(f"ASR task failed: {output}")

            raise ASRException("ASR task timeout")

    def _convert_asr_result(self, output: dict[str, Any]) -> dict[str, Any]:
        """
        转换 DashScope ASR 结果格式为兼容格式

        Args:
            output: DashScope 原始输出

        Returns:
            兼容格式的转录结果
        """
        logger = logging.getLogger(__name__)

        result = {"utterances": []}

        # 记录输出结构用于调试
        logger.info(f"ASR output keys: {list(output.keys())}")
        logger.info(f"results count: {len(output.get('results', []))}")
        logger.info(f"transcripts count: {len(output.get('transcripts', []))}")

        # 检查是否有 results 和 transcription_url[Any]
        results = output.get("results", [])
        if results:
            logger.info(f"First result keys: {list(results[0].keys()) if results[0] else 'empty'}")
            if results[0].get("transcription_url"):
                # 下载详细转录结果
                transcription_url = results[0]["transcription_url"]
                logger.info(f"Downloading transcription from: {transcription_url}")
                try:
                    response = httpx.get(transcription_url, timeout=60.0)
                    response.raise_for_status()
                    transcription = response.json()
                    logger.info(f"Downloaded transcription keys: {list(transcription.keys())}")
                    return self._process_transcription(transcription)
                except Exception as e:
                    # 下载失败，回退到直接处理
                    logger.warning(f"Failed to download transcription: {e}, falling back to transcripts")

        # 处理 transcripts
        transcripts = output.get("transcripts", [])
        logger.info(f"Processing {len(transcripts)} transcripts")
        return self._process_transcripts(transcripts)

    def _process_transcription(self, transcription: dict[str, Any]) -> dict[str, Any]:
        """处理已下载的转录结果"""
        result = {"utterances": []}

        # 检查 transcripts 数组
        channel_transcripts = transcription.get("transcripts", [])

        # 处理嵌套格式
        if channel_transcripts and isinstance(channel_transcripts[0], dict) and channel_transcripts[0].get("transcripts"):
            channel_transcripts = channel_transcripts[0]["transcripts"]

        for channel in channel_transcripts:
            inner_transcripts = channel.get("transcripts", [channel])

            for inner in inner_transcripts:
                utterance = {
                    "text": inner.get("text", ""),
                    "begin_time": 0,
                    "end_time": inner.get("content_duration_in_milliseconds", 0),
                    "words": [],
                }

                # 处理字级别时间戳
                for sentence in inner.get("sentences", []):
                    for word in sentence.get("words", []):
                        utterance["words"].append(
                            {
                                "text": word.get("text", word.get("word", "")),
                                "begin_time": round(word.get("begin_time", word.get("start_time", 0))),
                                "end_time": round(word.get("end_time", 0)),
                            }
                        )

                # 如果没有字级别时间戳，按字符拆分
                if not utterance["words"] and utterance["text"]:
                    chars = list(utterance["text"])
                    char_duration = utterance["end_time"] / len(chars) if chars else 0
                    for i, char in enumerate(chars):
                        utterance["words"].append(
                            {
                                "text": char,
                                "begin_time": round(i * char_duration),
                                "end_time": round((i + 1) * char_duration),
                            }
                        )

                if utterance["text"]:
                    result["utterances"].append(utterance)

        return result

    def _process_transcripts(self, transcripts: list) -> dict[str, Any]:
        """处理 transcripts 列表"""
        logger = logging.getLogger(__name__)

        result = {"utterances": []}

        logger.info(f"_process_transcripts: received {len(transcripts)} transcripts")

        # 处理嵌套格式
        if transcripts and isinstance(transcripts[0], dict) and transcripts[0].get("transcripts"):
            logger.info("Found nested transcripts format, extracting...")
            transcripts = transcripts[0]["transcripts"]
            logger.info(f"After extraction: {len(transcripts)} transcripts")

        for idx, channel in enumerate(transcripts):
            logger.info(f"Processing channel {idx}: keys = {list(channel.keys()) if isinstance(channel, dict) else type(channel)}")

            # 确保 channel 是字典
            if not isinstance(channel, dict):
                logger.warning(f"Channel {idx} is not a dict: {type(channel)}")
                continue

            inner_transcripts = channel.get("transcripts", [channel])
            logger.info(f"Channel {idx} has {len(inner_transcripts)} inner transcripts")

            for inner_idx, inner in enumerate(inner_transcripts):
                text = inner.get("text", "")
                logger.info(f"  Inner {inner_idx}: text = '{text[:50] if text else '(empty)'}...'")

                utterance = {
                    "text": text,
                    "begin_time": 0,
                    "end_time": inner.get("content_duration_in_milliseconds", 0),
                    "words": [],
                }

                # 处理字级别时间戳
                sentences = inner.get("sentences", [])
                if sentences:
                    logger.info(f"    Found {len(sentences)} sentences")

                for sentence in sentences:
                    words = sentence.get("words", [])
                    for word in words:
                        utterance["words"].append(
                            {
                                "text": word.get("text", word.get("word", "")),
                                "begin_time": round(word.get("begin_time", word.get("start_time", 0))),
                                "end_time": round(word.get("end_time", 0)),
                            }
                        )

                # 如果没有字级别时间戳，按字符拆分
                if not utterance["words"] and utterance["text"]:
                    chars = list(utterance["text"])
                    char_duration = utterance["end_time"] / len(chars) if chars else 0
                    for i, char in enumerate(chars):
                        utterance["words"].append(
                            {
                                "text": char,
                                "begin_time": round(i * char_duration),
                                "end_time": round((i + 1) * char_duration),
                            }
                        )

                if utterance["text"]:
                    result["utterances"].append(utterance)
                    logger.info(f"  Added utterance: {len(utterance['words'])} words")

        logger.info(f"_process_transcripts: returning {len(result['utterances'])} utterances")
        return result

    # ==================== OCR 图像识别 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def ocr(self, image_path: str) -> dict[str, Any]:
        """
        OCR 图像识别 - 使用 DashScope VL 模型

        Args:
            image_path: 图片文件路径（本地路径）

        Returns:
            OCR 识别结果，包含结构化信息
        """

        # 读取图片并转为 base64
        with open(image_path, "rb") as f:
            image_data = f.read()

        base64_image = base64.b64encode(image_data).decode()

        # 判断 MIME 类型
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        data_uri = f"data:{mime_type};base64,{base64_image}"

        # JS 版本使用的详细 prompt
        prompt = """请分析这张 PPT 图片，提取以下信息（JSON 格式）：

1. title: PPT 标题（通常是大号字体、居中的文字）
2. subtitles: 副标题或小节标题
3. body: 主要内容文字（数组，每段一个元素）
4. formulas: 公式（如有，保持原格式）
5. keyTerms: 关键术语或专业词汇

**重要**：JSON 中的反斜杠必须转义为双反斜杠（\\\\）。
例如：LaTeX 公式 $ \\omega $ 应写为 "$ \\\\omega $"

请直接返回 JSON 结构体，不要有其他说明文字和Markdown 标志。

格式：
{
  "title": "PPT标题",
  "subtitles": ["副标题1", "副标题2"],
  "body": ["正文段落1", "正文段落2"],
  "formulas": ["公式1", "公式2"],
  "keyTerms": ["术语1", "术语2"]
}"""

        # 修复：按照官方文档格式
        body = {
            "model": settings.dashscope_ocr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "enable_thinking": False,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{DASHSCOPE_BASE}/compatible-mode/v1/chat/completions",
                headers=self._get_headers(),
                json=body,
            )

            if response.status_code != 200:
                result = response.json()
                raise OCRException(f"OCR request failed: {result}")

            return self._parse_ocr_result(response.json())

    def _parse_ocr_result(self, response: dict[str, Any]) -> dict[str, Any]:
        """解析 OCR 结果"""
        try:
            content = response["choices"][0]["message"]["content"]

            # 移除 markdown 代码块标记
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接查找 JSON 对象
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    # 无法解析，使用原始文本
                    json_str = content

            try:
                parsed = json.loads(json_str)
                return {
                    "title": parsed.get("title", ""),
                    "subtitles": parsed.get("subtitles", []),
                    "body": parsed.get("body", []),
                    "formulas": parsed.get("formulas", []),
                    "keyTerms": parsed.get("keyTerms", []),
                    "rawText": content,
                    "parseError": False
                }
            except json.JSONDecodeError:
                # JSON 解析失败，返回原始文本
                return {
                    "title": "",
                    "subtitles": [],
                    "body": [content],
                    "formulas": [],
                    "keyTerms": [],
                    "rawText": content,
                    "parseError": True
                }
        except Exception as e:
            return {
                "title": "",
                "subtitles": [],
                "body": [],
                "formulas": [],
                "keyTerms": [],
                "rawText": "",
                "error": str(e)
            }

    async def ocr_batch(
        self,
        image_paths: list[str],
        concurrency: int = 5
    ) -> list[dict[str, Any]]:
        """
        批量 OCR 识别 - 处理本地图片文件

        Args:
            image_paths: 图片文件路径列表
            concurrency: 并发数

        Returns:
            OCR 识别结果列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(path: str) -> dict[str, Any]:
            async with semaphore:
                try:
                    return await self.ocr(path)
                except Exception as e:
                    return {"error": str(e), "path": path}

        tasks = [process_one(path) for path in image_paths]
        return await asyncio.gather(*tasks)

    # ==================== LLM 文本生成 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """
        LLM 文本生成 (OpenAI 兼容格式)

        Args:
            prompt: 提示词
            max_tokens: 最大生成长度
            temperature: 温度参数

        Returns:
            生成的文本
        """
        body = {
            "model": settings.dashscope_llm_model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{DASHSCOPE_BASE}/compatible-mode/v1/chat/completions",
                headers=self._get_headers(),
                json=body,
            )

            if response.status_code != 200:
                result = response.json()
                raise LLMException(f"LLM request failed: {result}")

            result = response.json()
            text = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return text

    async def classify_batch(
        self,
        sentences: list[dict[str, Any]],
        ppt_context: list[dict[str, Any]] | None = None,
        batch_size: int = 50,
    ) -> list[dict[str, Any]]:
        """
        批量内容分类

        Args:
            sentences: 句子列表，每个包含 text, begin_time, end_time
            ppt_context: PPT 上下文
            batch_size: 批处理大小

        Returns:
            分类结果列表
        """
        

        # 构建 PPT 上下文
        context_str = ""
        if ppt_context:
            ppt_items = []
            for p in ppt_context[:5]:
                title = p.get('title', '')
                content = p.get('text', '') or p.get('content', '')
                if title or content:
                    ppt_items.append(f"- {title}: {content}")
            if ppt_items:
                context_str = "\n\n## PPT 上下文\n\n" + "\n".join(ppt_items)

        results = []

        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]

            batch_text = "\n".join([f"{j+1}. {s['text']}" for j, s in enumerate(batch)])

            # 使用规则文件中的详细分类标准
            prompt = f"""你是一个课程内容分类助手。请根据以下规则对每个句子进行分类。

## 分类标签

### 1. core (核心知识) - 必须保留
- 定义概念：包含"定义是"、"公式是"、"定理是"
- 公式定理：包含"等于"、"称为"、"记作"、数学表达式
- 重要结论：关键概念首次出现
- 核心原理：步骤/流程的核心描述

### 2. explain (解释说明) - 可选保留
- 举例说明：包含"比如说"、"举个例子"、"换句话说"
- 类比解释：包含"意思是"、"也就是说"
- 补充细节：对前文内容的进一步解释
- 具体案例分析

### 3. interact (课堂互动) - 建议删除
- 师生问答：包含人名（学生名）、"谁来说"、"你来回答"
- 期待回应：包含"对不对"、"是不是"、"听懂了吗"
- 学生发言：学生回答问题、课堂讨论

### 4. chat (闲聊跑题) - 必须删除
- 课程无关：与当前知识点无关的内容
- 跑题内容：个人经历、轶事（非教学目的）
- 课堂管理：作业、考试、考勤、纪律相关
- 无意义内容：纯语气词、"啊"、"嗯"、"呃"、"哈哈哈哈"

### 5. transition (过渡语) - 可以删除
- 承上启下：纯过渡词"那么"、"接下来"、"下面"
- 填充语句："所以说呢"、"这个呢就是说"
- 重复强调：无实质内容的"这个很重要"、"一定要记住"

## 分类优先级

当一句话可能属于多个类别时，按以下优先级判断：
```
core > explain > interact > chat > transition
```

## 边界情况处理原则

**宁可保留，不要误删**：
- 不确定的内容 → explain（可选保留）
- 疑似核心知识 → core（保留）
- 混合内容按主体内容分类{context_str}

## 待分类句子

{batch_text}

## 输出格式

请返回 JSON 格式，每个句子包含：
- idx: 句子序号（从0开始）
- label: 分类标签 (core/explain/interact/chat/transition)
- confidence: 置信度 (0-1)
- reason: 简短的分类理由

```json
[
  {{"idx": 0, "label": "core", "confidence": 0.95, "reason": "包含定义性陈述"}},
  ...
]
```"""

            try:
                response_text = await self.generate_text(prompt, max_tokens=4096)

                # 解析 JSON 响应
                code_block_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
                if code_block_match:
                    json_text = code_block_match.group(1)
                else:
                    # 尝试直接解析
                    array_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                    if array_match:
                        json_text = array_match.group(0)
                    else:
                        json_text = response_text

                batch_results = json.loads(json_text)
                # 将分类结果与原始句子数据合并，保留原始字段 (text, begin_time, end_time 等)
                # 使用 idx 字段来匹配原始句子，而不是数组索引
                # 参考 scripts/classify_content.js:258-270 的实现
                for result_item in batch_results:
                    idx = result_item.get("idx")
                    if idx is not None:
                        # 找到对应的原始句子
                        original_sentence = next((s for s in batch if s.get("idx") == idx), None)
                        if original_sentence:
                            merged_result = {
                                **original_sentence,  # 保留原始句子的所有字段
                                "label": result_item.get("label", "explain"),
                                "confidence": result_item.get("confidence", 0.5),
                                "reason": result_item.get("reason", ""),
                            }
                            results.append(merged_result)

            except json.JSONDecodeError as e:
                logging.getLogger(__name__).warning(
                    f"JSON 解析失败 (batch {i}): {e}, 默认标记为 explain"
                )
                # 失败时默认为 explain，但保留原始句子数据
                for sentence in batch:
                    results.append({
                        **sentence,
                        "label": "explain",
                        "confidence": 0.5,
                        "reason": f"JSON 解析失败: {e}",
                    })
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"分类请求失败 (batch {i}): {e}, 默认标记为 explain"
                )
                # 网络错误等其他异常，也降级处理
                for sentence in batch:
                    results.append({
                        **sentence,
                        "label": "explain",
                        "confidence": 0.5,
                        "reason": f"分类请求失败: {e}",
                    })

        return results

    # ==================== TTS 语音合成 ====================

    async def tts(
        self,
        text: str,
        voice: str | None = None,
        model: str | None = None,
    ) -> bytes:
        """
        TTS 语音合成

        Args:
            text: 要合成的文本
            voice: 音色，默认从配置读取
            model: 模型，默认从配置读取

        Returns:
            音频数据 (bytes)
        """
        voice = voice or settings.tts_voice
        model = model or settings.dashscope_tts_model

        body = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation",
                headers=self._get_headers(),
                json=body,
            )

            if response.status_code != 200:
                result = response.json()
                raise TTSException(f"TTS request failed: {result}")

            result = response.json()
            output = result.get("output", {})

            # 如果有 URL，下载音频
            if output.get("audio", {}).get("url"):
                audio_url = output["audio"]["url"]
                audio_response = await client.get(audio_url)
                return audio_response.content

            # 如果有 Base64 数据
            if output.get("audio", {}).get("data"):
                
                return base64.b64decode(output["audio"]["data"])

            raise TTSException(f"Unexpected TTS response format: {result}")

    async def tts_batch(
        self,
        texts: list[str],
        voice: str | None = None,
        model: str | None = None,
        output_dir: str | None = None,
        concurrency: int = 3,
    ) -> list[str]:
        """
        批量 TTS 合成

        Args:
            texts: 文本列表
            voice: 音色
            model: 模型名称（可选）
            output_dir: 输出目录（可选，如果指定则保存到文件）
            concurrency: 并发数

        Returns:
            如果指定 output_dir，返回音频文件路径列表；否则返回音频数据列表
        """

        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(index: int, text: str) -> bytes | str:
            async with semaphore:
                audio_data = await self.tts(text, voice, model)

                # 如果指定了输出目录，保存到文件
                if output_dir:
                    output_path = Path(output_dir)
                    output_path.mkdir(parents=True, exist_ok=True)
                    audio_file = output_path / f"segment_{index:05d}.mp3"

                    with open(audio_file, "wb") as f:
                        f.write(audio_data)

                    return str(audio_file)

                return audio_data

        tasks = [process_one(i, text) for i, text in enumerate(texts)]
        return await asyncio.gather(*tasks)


# 全局客户端实例
_dashscope_client: DashScopeClient | None = None


def get_dashscope_client() -> DashScopeClient:
    """获取 DashScope 客户端单例"""
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = DashScopeClient()
    return _dashscope_client
