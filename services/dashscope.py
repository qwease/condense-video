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
                    return self._convert_asr_result(output)
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
        result = {"utterances": []}

        # 检查是否有 results
        results = output.get("results", [])
        if results and results[0].get("transcription_url"):
            # 需要下载详细结果 (这里简化处理，实际需要下载)
            # 由于需要额外下载，这里返回基本格式
            pass

        # 处理 transcripts
        transcripts = output.get("transcripts", [])

        # 处理嵌套格式
        if transcripts and isinstance(transcripts[0], dict) and transcripts[0].get("transcripts"):
            transcripts = transcripts[0]["transcripts"]

        for channel in transcripts:
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

    # ==================== OCR 图像识别 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def ocr(self, image_url: str) -> dict[str, Any]:
        """
        OCR 图像识别

        Args:
            image_url: 图片 URL

        Returns:
            OCR 识别结果
        """
        body = {
            "model": settings.dashscope_ocr_model,
            "input": {
                "image": image_url,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{DASHSCOPE_BASE}/api/v1/services/vd/image/understanding",
                headers=self._get_headers(),
                json=body,
            )

            if response.status_code != 200:
                result = response.json()
                raise OCRException(f"OCR request failed: {result}")

            return response.json()

    async def ocr_batch(self, image_urls: list[str], concurrency: int = 5) -> list[dict[str, Any]]:
        """
        批量 OCR 识别

        Args:
            image_urls: 图片 URL 列表
            concurrency: 并发数

        Returns:
            OCR 识别结果列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(url: str) -> dict[str, Any]:
            async with semaphore:
                return await self.ocr(url)

        tasks = [process_one(url) for url in image_urls]
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
        # 构建 prompt
        context_str = ""
        if ppt_context:
            context_str = "\n\nPPT 内容:\n" + "\n".join(
                [f"- {p.get('title', '')}: {p.get('text', '')}" for p in ppt_context[:5]]
            )

        results = []

        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]

            batch_text = "\n".join([f"{i+1}. {s['text']}" for i, s in enumerate(batch)])

            prompt = f"""请对以下句子进行分类，判断每个句子属于哪一类：

标签定义：
- core: 核心知识 (定义、公式、定理、重要概念)
- explain: 解释说明 (对核心内容的解释、举例)
- interact: 课堂互动 (师生互动、提问、回答)
- chat: 闲聊跑题 (与课程无关的内容)
- transition: 过渡语 (承上启下的过渡语句)

{context_str}

句子：
{batch_text}

请返回 JSON 格式，每个句子包含：
- idx: 句子序号
- label: 分类标签
- confidence: 置信度 (0-1)

格式：
```json
[
  {{"idx": 0, "label": "core", "confidence": 0.95}},
  ...
]
```"""

            try:
                response_text = await self.generate_text(prompt, max_tokens=4096)

                # 解析 JSON 响应
                import json
                import re

                json_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)
                else:
                    # 尝试直接解析
                    json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                    if json_match:
                        response_text = json_match.group(0)

                batch_results = json.loads(response_text)
                results.extend(batch_results)

            except (json.JSONDecodeError, KeyError) as e:
                # 失败时默认为 explain
                for j, _ in enumerate(batch):
                    results.append(
                        {"idx": i + j, "label": "explain", "confidence": 0.5}
                    )

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
                import base64
                return base64.b64decode(output["audio"]["data"])

            raise TTSException(f"Unexpected TTS response format: {result}")

    async def tts_batch(
        self,
        texts: list[str],
        voice: str | None = None,
        concurrency: int = 3,
    ) -> list[bytes]:
        """
        批量 TTS 合成

        Args:
            texts: 文本列表
            voice: 音色
            concurrency: 并发数

        Returns:
            音频数据列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(text: str) -> bytes:
            async with semaphore:
                return await self.tts(text, voice)

        tasks = [process_one(text) for text in texts]
        return await asyncio.gather(*tasks)


# 全局客户端实例
_dashscope_client: DashScopeClient | None = None


def get_dashscope_client() -> DashScopeClient:
    """获取 DashScope 客户端单例"""
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = DashScopeClient()
    return _dashscope_client
