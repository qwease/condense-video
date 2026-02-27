"""
配置管理模块测试
"""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import AppConfig, DashScopeConfig


class TestAppConfig:
    """AppConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = AppConfig()

        assert config.api_host == "0.0.0.0"
        assert config.api_port == 8000
        assert config.api_workers == 1
        assert config.api_reload is False
        assert config.api_debug is False

    def test_redis_config(self):
        """测试 Redis 配置"""
        config = AppConfig()

        assert config.redis_url == "redis://redis:6379/0"
        assert config.redis_progress_ttl == 604800  # 7 天
        assert config.redis_result_ttl == 2592000  # 30 天

    def test_dashscope_config(self):
        """测试 DashScope 配置"""
        # 使用环境变量设置 API key
        os.environ["DASHSCOPE_API_KEY"] = "sk-test123456789"
        config = AppConfig()

        assert config.dashscope_api_key == "sk-test123456789"
        assert config.dashscope_asr_model == "paraformer-v2"
        assert config.dashscope_ocr_model == "qwen-vl-plus"
        assert config.dashscope_llm_model == "qwen-plus"
        assert config.dashscope_tts_model == "qwen3-tts-flash"

        # 清理环境变量
        del os.environ["DASHSCOPE_API_KEY"]

    def test_dashscope_api_key_validation(self):
        """测试 DashScope API key 验证"""
        # 无效的 API key (不以 sk- 开头)
        with pytest.raises(ValidationError):
            AppConfig(dashscope_api_key="invalid-key")

        # 有效的 API key
        config = AppConfig(dashscope_api_key="sk-test123456789")
        assert config.dashscope_api_key == "sk-test123456789"

    def test_cutting_modes_property(self):
        """测试剪辑模式配置"""
        config = AppConfig()

        cutting_modes = config.cutting_modes

        assert "essential" in cutting_modes
        assert "complete" in cutting_modes
        assert cutting_modes["essential"]["delete_labels"] == ["interact", "chat", "transition"]
        assert cutting_modes["complete"]["delete_labels"] == ["chat"]

    def test_dashscope_property(self):
        """测试 DashScope 配置对象属性"""
        config = AppConfig(dashscope_api_key="sk-test")

        dashscope = config.dashscope

        assert isinstance(dashscope, DashScopeConfig)
        assert dashscope.api_key == "sk-test"
        assert dashscope.asr_model == "paraformer-v2"

    def test_storage_backend_config(self):
        """测试存储后端配置"""
        config = AppConfig()

        assert config.storage_backend == "local"
        assert config.storage_path == "./data"

    def test_tts_config(self):
        """测试 TTS 配置"""
        config = AppConfig()

        assert config.tts_engine == "dashscope"
        assert config.tts_voice == "Cherry"
        assert config.tts_max_length == 300
        assert config.tts_concurrency == 3

    def test_ocr_config(self):
        """测试 OCR 配置"""
        config = AppConfig()

        assert config.ocr_model == "qwen-vl-plus"
        assert config.ocr_concurrency == 5
        assert config.ocr_rpm == 60

    def test_classification_config(self):
        """测试分类配置"""
        config = AppConfig()

        assert config.classification_model == "qwen-plus"
        assert config.classification_concurrency == 10
        assert config.classification_batch_size == 50


class TestDashScopeConfig:
    """DashScopeConfig 测试"""

    def test_create_dashscope_config(self):
        """测试创建 DashScope 配置"""
        config = DashScopeConfig(
            api_key="sk-test",
            asr_model="paraformer-v2",
            ocr_model="qwen-vl-plus",
            llm_model="qwen-plus",
            tts_model="qwen3-tts-flash",
        )

        assert config.api_key == "sk-test"
        assert config.asr_model == "paraformer-v2"
        assert config.ocr_model == "qwen-vl-plus"
        assert config.llm_model == "qwen-plus"
        assert config.tts_model == "qwen3-tts-flash"
        assert config.rpm == 60
        assert config.retry_times == 3
        assert config.retry_delay == 1000
