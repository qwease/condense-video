"""
Pytest 配置和共享 fixtures
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def test_data_dir():
    """测试数据目录"""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_video_path(test_data_dir):
    """示例视频文件路径"""
    return test_data_dir / "sample_video.mp4"


@pytest.fixture
def sample_audio_path(test_data_dir):
    """示例音频文件路径"""
    return test_data_dir / "sample_audio.mp3"


@pytest.fixture
def sample_frames_dir(test_data_dir):
    """示例帧目录"""
    return test_data_dir / "frames"


@pytest.fixture
def mock_dashscope_client():
    """DashScope 客户端 mock"""
    from unittest.mock import AsyncMock, MagicMock

    mock_client = MagicMock()

    # ASR mock
    mock_client.asr_transcribe = AsyncMock(return_value={
        "transcript": "这是测试转录结果",
        "utterances": [
            {"text": "你好", "begin_time": 0, "end_time": 500},
            {"text": "世界", "begin_time": 500, "end_time": 1000},
        ],
    })

    # OCR mock
    mock_client.ocr_image = AsyncMock(return_value={
        "text": "测试 OCR 结果",
        "structure": {"title": "测试标题"},
    })

    # LLM mock
    mock_client.llm_classify = AsyncMock(return_value={
        "label": "core",
        "confidence": 0.9,
    })

    # TTS mock
    mock_client.tts_synthesize = AsyncMock(return_value=b"mock audio data")

    return mock_client


@pytest.fixture
def mock_redis(monkeypatch):
    """Redis 客户端 mock"""
    import redis
    from services import redis_client

    mock_redis_instance = MagicMock()

    # Redis 基本方法
    mock_redis_instance.ping.return_value = True
    mock_redis_instance.hset.return_value = True
    mock_redis_instance.hgetall.return_value = {}
    mock_redis_instance.set.return_value = True
    mock_redis_instance.get.return_value = None
    mock_redis_instance.publish.return_value = 0
    mock_redis_instance.delete.return_value = 1
    mock_redis_instance.scan_iter.return_value = iter([])
    mock_redis_instance.expire.return_value = True

    monkeypatch.setattr(redis_client, "redis", mock_redis_instance)
    monkeypatch.setattr(redis_client, "get_redis", lambda: mock_redis_instance)


@pytest.fixture
def mock_storage():
    """存储 mock"""
    from core.storage import StorageBackend

    mock_storage = MagicMock(spec=StorageBackend)
    mock_storage.health_check.return_value = True
    mock_storage.upload_file.return_value = "http://example.com/file.mp4"
    mock_storage.download_file.return_value = b"file content"

    return mock_storage


@pytest.fixture
def sample_transcript_data():
    """示例转录数据"""
    return {
        "utterances": [
            {
                "text": "传递函数的定义是零初始条件下输出与输入之比",
                "begin_time": 320,
                "end_time": 5660,
                "words": [
                    {"text": "传", "begin_time": 320, "end_time": 400},
                    {"text": "递", "begin_time": 400, "end_time": 480},
                    {"text": "函", "begin_time": 480, "end_time": 560},
                    {"text": "数", "begin_time": 560, "end_time": 640},
                ],
            },
            {
                "text": "这是一个非常重要的概念",
                "begin_time": 6000,
                "end_time": 8000,
                "words": [],
            },
        ]
    }


@pytest.fixture
def sample_classification_data():
    """示例分类数据"""
    return {
        "segments": [
            {
                "idx": 0,
                "text": "传递函数的定义是零初始条件下输出与输入之比",
                "start_idx": 0,
                "end_idx": 10,
                "start_time": 0.32,
                "end_time": 5.66,
                "label": "core",
                "confidence": 0.95,
                "reason": "这是定义性陈述",
            },
            {
                "idx": 1,
                "text": "大家听懂了吗",
                "start_idx": 11,
                "end_idx": 13,
                "start_time": 6.0,
                "end_time": 8.0,
                "label": "interact",
                "confidence": 0.9,
                "reason": "这是互动提问",
            },
        ],
        "statistics": {
            "total": 2,
            "core": 1,
            "explain": 0,
            "interact": 1,
            "chat": 0,
            "transition": 0,
        },
    }


@pytest.fixture
def sample_ppt_data():
    """示例 PPT 数据"""
    return {
        "video_info": {
            "path": "lecture.mp4",
            "duration": 5569.99,
            "fps": 30,
        },
        "slides": [
            {
                "frame_id": 1,
                "frame_path": "frames/frame_00001.jpg",
                "timestamp": 0.0,
                "ocr_text": "第三章 控制系统的时域分析\n3.1 时域分析基础",
                "structure": {
                    "title": "控制系统的时域分析",
                    "subtitles": ["3.1 时域分析基础"],
                    "body": [],
                    "formulas": [],
                    "key_terms": ["时域分析", "控制系统"],
                    "confidence": 0.92,
                },
            }
        ],
    }
