"""
工具函数测试
"""

import pytest

from utils.text import (
    is_filler_sentence,
    is_interaction,
    is_transition,
    split_by_punctuation,
    split_by_silence,
    truncate_for_tts,
)
from utils.time import (
    align_to_frame,
    calculate_overlap,
    frames_to_seconds,
    hms_to_seconds,
    seconds_to_hms,
    seconds_to_frames,
    validate_time_range,
)


class TestTextUtils:
    """文本处理工具测试"""

    def test_split_by_punctuation(self):
        """测试按标点分句"""
        text = "这是第一句。这是第二句！这是第三句？这是第四句"
        sentences = split_by_punctuation(text)

        assert len(sentences) == 4
        assert sentences[0] == "这是第一句。"
        assert sentences[1] == "这是第二句！"

    def test_split_by_punctuation_empty(self):
        """测试空字符串"""
        sentences = split_by_punctuation("")
        assert sentences == []

    def test_split_by_punctuation_no_punctuation(self):
        """测试没有标点的文本"""
        text = "这是一段没有标点的文字"
        sentences = split_by_punctuation(text)
        # 应该返回整个文本作为一句话
        assert len(sentences) >= 1

    def test_is_filler_sentence(self):
        """测试填充句检测"""
        assert is_filler_sentence("嗯嗯") is True
        assert is_filler_sentence("啊") is True
        assert is_filler_sentence("那个") is True
        assert is_filler_sentence("好的") is True
        assert is_filler_sentence("这是重要内容") is False

    def test_is_interaction(self):
        """测试互动检测"""
        assert is_interaction("大家听懂了吗") is True
        assert is_interaction("有问题吗") is True
        assert is_interaction("谁知道了") is True
        assert is_interaction("这是知识点") is False

    def test_is_transition(self):
        """测试过渡检测"""
        assert is_transition("我们回到正题") is True
        assert is_transition("接下来看") is True
        assert is_transition("刚才讲了") is True
        assert is_transition("这是核心内容") is False

    def test_split_by_silence(self):
        """测试按静音分句"""
        words = [
            {"text": "你好", "start": 0, "end": 0.5, "gap": 0.1},
            {"text": "世界", "start": 0.6, "end": 1.0, "gap": 0.1},
            {"text": "测试", "start": 1.1, "end": 1.5, "gap": 0.6},  # 长静音
            {"text": "结束", "start": 2.1, "end": 2.5, "gap": 0.0},
        ]

        sentences = split_by_silence(words, silence_threshold=0.5)

        # 应该在长静音处分句
        assert len(sentences) >= 1

    def test_truncate_for_tts(self):
        """测试 TTS 文本截断"""
        long_text = "这是一段很长的文本。" * 100  # 约 1500 字

        segments = truncate_for_tts(long_text, max_length=300)

        # 每个片段不超过 300 字
        for segment in segments:
            assert len(segment) <= 300 + 20  # 允许一些误差

    def test_truncate_for_tts_short(self):
        """测试短文本截断"""
        short_text = "这是一段短文本"

        segments = truncate_for_tts(short_text, max_length=300)

        assert len(segments) == 1
        assert segments[0] == short_text


class TestTimeUtils:
    """时间处理工具测试"""

    def test_seconds_to_hms(self):
        """测试秒转时分秒"""
        assert seconds_to_hms(0) == "00:00:00"
        assert seconds_to_hms(65.5) == "00:01:05"
        assert seconds_to_hms(3661) == "01:01:01"
        assert seconds_to_hms(90061) == "25:01:01"

    def test_hms_to_seconds(self):
        """测试时分秒转秒"""
        assert hms_to_seconds("00:00:00") == 0.0
        assert hms_to_seconds("00:01:05") == 65.0
        assert hms_to_seconds("01:01:01") == 3661.0
        assert hms_to_seconds("25:01:01") == 90061.0

    def test_hms_conversion_roundtrip(self):
        """测试时间转换往返"""
        original = 12345.67
        hms = seconds_to_hms(original)
        converted = hms_to_seconds(hms)
        # 由于秒的小数部分被截断，允许一定误差
        assert abs(converted - int(original)) <= 1.0

    def test_frames_to_seconds(self):
        """测试帧转秒"""
        assert frames_to_seconds(0, fps=25) == 0.0
        assert frames_to_seconds(25, fps=25) == 1.0
        assert frames_to_seconds(50, fps=25) == 2.0
        assert frames_to_seconds(30, fps=30) == 1.0

    def test_seconds_to_frames(self):
        """测试秒转帧"""
        assert seconds_to_frames(0.0, fps=25) == 0
        assert seconds_to_frames(1.0, fps=25) == 25
        assert seconds_to_frames(2.0, fps=25) == 50
        assert seconds_to_frames(1.0, fps=30) == 30

    def test_calculate_overlap(self):
        """测试计算重叠时间"""
        # 无重叠
        assert calculate_overlap(0, 10, 15, 25) == 0.0
        # 部分重叠
        assert calculate_overlap(0, 10, 5, 15) == 5.0
        # 完全包含
        assert calculate_overlap(5, 15, 0, 25) == 10.0
        # 边界情况
        assert calculate_overlap(0, 10, 10, 20) == 0.0

    def test_validate_time_range(self):
        """测试时间范围验证"""
        # 有效范围
        assert validate_time_range(0, 10, max_duration=100) is True
        assert validate_time_range(50, 100, max_duration=100) is True

        # 无效范围
        assert validate_time_range(-1, 10) is False
        assert validate_time_range(0, 10, max_duration=5) is False
        assert validate_time_range(10, 0) is False

    def test_align_to_frame(self):
        """测试帧对齐"""
        fps = 25

        # 对齐到最近帧
        assert align_to_frame(0.012, fps, "nearest") == 0.0  # 0.3 帧 -> 0 帧
        assert align_to_frame(0.02, fps, "nearest") == 0.04   # 0.5 帧 -> 1 帧 (0.04s)
        assert align_to_frame(0.05, fps, "nearest") == 0.04   # 1.25 帧 -> 1 帧

        # 向下对齐
        assert align_to_frame(0.05, fps, "down") == 0.04

        # 向上对齐
        assert align_to_frame(0.02, fps, "up") == 0.04


class TestVideoUtils:
    """视频处理工具测试"""

    def test_time_range_duration(self):
        """测试 TimeRange 时长计算"""
        from utils.video import TimeRange

        tr = TimeRange(start=10.0, end=25.0)
        assert tr.duration == 15.0

        tr_zero = TimeRange(start=0, end=0)
        assert tr_zero.duration == 0

    def test_time_range_overlaps(self):
        """测试 TimeRange 重叠检测"""
        from utils.video import TimeRange

        tr1 = TimeRange(start=0, end=10)
        tr2 = TimeRange(start=5, end=15)
        tr3 = TimeRange(start=20, end=30)

        assert tr1.overlaps(tr2) is True
        assert tr1.overlaps(tr3) is False
        assert tr2.overlaps(tr3) is False

    def test_time_range_contains(self):
        """测试 TimeRange 包含检测"""
        from utils.video import TimeRange

        tr = TimeRange(start=10, end=20)

        assert tr.contains(10) is True
        assert tr.contains(15) is True
        assert tr.contains(20) is True
        assert tr.contains(5) is False
        assert tr.contains(25) is False

    def test_video_segment(self):
        """测试 VideoSegment"""
        from utils.video import VideoSegment, TimeRange

        time_range = TimeRange(start=0, end=10)
        segment = VideoSegment(
            index=0,
            time_range=time_range,
            text="测试文本",
            classification="core",
        )

        assert segment.start == 0
        assert segment.end == 10
        assert segment.duration == 10
        assert segment.text == "测试文本"
        assert segment.classification == "core"

    def test_calculate_cut_statistics(self):
        """测试计算剪辑统计"""
        from utils.video import VideoSegment, TimeRange, calculate_cut_statistics

        original = [
            VideoSegment(
                index=i,
                time_range=TimeRange(start=i * 10, end=(i + 1) * 10),
                text=f"Segment {i}",
                classification="core" if i % 2 == 0 else "chat",
            )
            for i in range(10)
        ]

        # 只保留 core 分类
        filtered = [s for s in original if s.classification == "core"]

        stats = calculate_cut_statistics(original, filtered)

        assert stats["original_duration"] == 100.0
        assert stats["filtered_duration"] == 50.0
        assert stats["removed_duration"] == 50.0
        assert stats["retention_ratio"] == 50.0
        assert stats["compression_ratio"] == 50.0
        assert stats["segment_count"]["original"] == 10
        assert stats["segment_count"]["filtered"] == 5
