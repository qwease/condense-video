"""
文本处理工具模块

提供视频文稿处理相关的工具函数：
- 句子分割
- 标点符号处理
- 文本清理
- 智能分句
- 文本摘要
"""

import re
from typing import Any


# 中文句子结束标点
SENTENCE_DELIMITERS = set("。！？.!?!？!；;")

# 中文静音分句阈值（秒）
SILENCE_THRESHOLD = 0.5

# 常见语气词（用于识别闲聊）
FILLER_WORDS = {
    "啊", "嗯", "呃", "额", "那个", "这个", "就是", "然后呢",
    "对吧", "是吧", "好的", "行", "行吧", "好", "好吧",
}

# 课堂互动关键词
INTERACTION_KEYWORDS = {
    "举手", "谁来说", "谁来回答", "谁知道", "有没有",
    "提问", "问题", "回答", "说一下", "来讲讲",
    "作业", "考试", "分数", "成绩", "交作业",
}

# 过渡语关键词
TRANSITION_KEYWORDS = {
    "接下来", "下面", "然后呢", "接着", "再看",
    "我们继续", "我们来看", "回到", "刚才说到",
}


def clean_text(text: str) -> str:
    """
    清理文本（去除多余空格、特殊字符等）

    Args:
        text: 原始文本

    Returns:
        清理后的文本
    """
    if not text:
        return ""

    # 去除首尾空白
    text = text.strip()

    # 替换多个空格为单个空格
    text = re.sub(r"\s+", " ", text)

    # 去除控制字符
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)

    # 去除特殊标点前后的空格
    text = re.sub(r"\s+([，。！？；：、""''（）【】])", r"\1", text)

    return text


def is_sentence_end(text: str) -> bool:
    """
    检查文本是否以句子结束标点结尾

    Args:
        text: 文本

    Returns:
        是否以句子结束标点结尾
    """
    if not text:
        return False

    return text[-1] in SENTENCE_DELIMITERS


def split_by_punctuation(text: str) -> list[str]:
    """
    按标点符号分割句子

    Args:
        text: 原始文本

    Returns:
        句子列表
    """
    if not text:
        return []

    sentences = []
    current = ""

    for char in text:
        current += char
        if char in SENTENCE_DELIMITERS:
            sentence = clean_text(current)
            if sentence:
                sentences.append(sentence)
            current = ""

    # 处理剩余内容
    if current:
        sentence = clean_text(current)
        if sentence:
            sentences.append(sentence)

    return sentences


def split_by_silence(
    words: list[dict[str, Any]],
    silence_threshold: float = SILENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    根据静音分割句子

    Args:
        words: 字级别字幕列表，每个元素包含 text, start_time, end_time, silence
        silence_threshold: 静音阈值（秒）

    Returns:
        句子列表
    """
    if not words:
        return []

    sentences = []
    current_words = []
    last_end_time = 0

    for word in words:
        # 检查静音
        if word.get("silence", False):
            # 计算与前一个字的间隔
            gap = word.get("start_time", 0) - last_end_time

            if gap >= silence_threshold and current_words:
                # 形成句子
                sentence = _words_to_sentence(current_words)
                if sentence:
                    sentences.append(sentence)
                current_words = []

        current_words.append(word)
        last_end_time = word.get("end_time", word.get("start_time", 0))

    # 处理剩余
    if current_words:
        sentence = _words_to_sentence(current_words)
        if sentence:
            sentences.append(sentence)

    return sentences


def _words_to_sentence(words: list[dict[str, Any]]) -> dict[str, Any]:
    """将字列表转换为句子字典"""
    if not words:
        return {}

    text = "".join(w.get("text", "") for w in words)
    start_time = words[0].get("start_time", 0)
    end_time = words[-1].get("end_time", start_time)

    return {
        "text": text,
        "start": start_time,
        "end": end_time,
        "words": words,
    }


def smart_sentence_split(
    words: list[dict[str, Any]],
    silence_threshold: float = SILENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    智能分句（结合标点和静音）

    Args:
        words: 字级别字幕列表
        silence_threshold: 静音阈值（秒）

    Returns:
        句子列表
    """
    if not words:
        return []

    sentences = []
    current_words = []
    last_end_time = 0

    for word in words:
        text = word.get("text", "")
        current_words.append(word)

        # 检查是否应该分句
        should_split = False

        # 条件1: 句子结束标点
        if text and text[-1] in SENTENCE_DELIMITERS:
            should_split = True

        # 条件2: 长静音（非标点结束时）
        elif word.get("silence", False):
            gap = word.get("start_time", 0) - last_end_time
            if gap >= silence_threshold and len(current_words) > 1:
                should_split = True

        if should_split:
            sentence = _words_to_sentence(current_words)
            if sentence:
                sentences.append(sentence)
            current_words = []

        last_end_time = word.get("end_time", word.get("start_time", 0))

    # 处理剩余
    if current_words:
        sentence = _words_to_sentence(current_words)
        if sentence:
            sentences.append(sentence)

    return sentences


def is_filler_sentence(text: str) -> bool:
    """
    检查是否为填充句（纯语气词）

    Args:
        text: 句子文本

    Returns:
        是否为填充句
    """
    if not text:
        return True

    # 去除标点和空格
    cleaned = re.sub(r"[^\w]", "", text)

    # 纯语气词
    if cleaned in FILLER_WORDS:
        return True

    # 大部分是语气词
    words = list(cleaned)
    filler_count = sum(1 for w in words if w in FILLER_WORDS)
    if len(words) > 0 and filler_count / len(words) > 0.7:
        return True

    return False


def is_interaction(text: str) -> bool:
    """
    检查是否包含课堂互动内容

    Args:
        text: 句子文本

    Returns:
        是否为互动内容
    """
    if not text:
        return False

    text_lower = text.lower()
    return any(keyword in text_lower for keyword in INTERACTION_KEYWORDS)


def is_transition(text: str) -> bool:
    """
    检查是否为过渡语

    Args:
        text: 句子文本

    Returns:
        是否为过渡语
    """
    if not text:
        return False

    text_lower = text.lower()
    return any(keyword in text_lower for keyword in TRANSITION_KEYWORDS)


def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """
    提取关键词（简单基于词频）

    Args:
        text: 文本
        top_n: 返回前N个关键词

    Returns:
        关键词列表
    """
    if not text:
        return []

    # 简单分词（按空格和标点）
    words = re.split(r"[\s，。！？；：、""''（）【】]+", text)

    # 过滤停用词
    stopwords = {"的", "了", "是", "在", "和", "与", "或", "但", "而", "等", "很", "也", "都"}
    keywords = [w for w in words if len(w) > 1 and w not in stopwords]

    # 统计词频
    freq = {}
    for word in keywords:
        freq[word] = freq.get(word, 0) + 1

    # 排序
    sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)

    return [word for word, _ in sorted_keywords[:top_n]]


def merge_sentences(
    sentences: list[str],
    max_length: int = 100,
    separator: str = " ",
) -> list[str]:
    """
    合并短句

    Args:
        sentences: 句子列表
        max_length: 最大合并长度
        separator: 连接符

    Returns:
        合并后的句子列表
    """
    if not sentences:
        return []

    merged = []
    current = sentences[0] if sentences else ""

    for sentence in sentences[1:]:
        if len(current) + len(separator) + len(sentence) <= max_length:
            current += separator + sentence
        else:
            merged.append(current)
            current = sentence

    if current:
        merged.append(current)

    return merged


def format_sentence_index(
    index: int,
    start_idx: int,
    end_idx: int,
    text: str,
) -> str:
    """
    格式化句子索引（用于 sentences.txt）

    Args:
        index: 句子索引
        start_idx: 起始字索引
        end_idx: 结束字索引
        text: 句子文本

    Returns:
        格式化的字符串
    """
    return f"{index}|{start_idx}-{end_idx}|{text}"


def parse_sentence_index(line: str) -> dict[str, Any] | None:
    """
    解析句子索引行

    Args:
        line: 格式为 "idx|startIdx-endIdx|text"

    Returns:
        解析后的字典或 None
    """
    parts = line.strip().split("|")
    if len(parts) < 3:
        return None

    try:
        index = int(parts[0])
        idx_range = parts[1].split("-")
        start_idx = int(idx_range[0])
        end_idx = int(idx_range[1])
        text = "|".join(parts[2:])  # 处理文本中可能存在的 |

        return {
            "index": index,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "text": text,
        }
    except (ValueError, IndexError):
        return None


def create_condensed_text(
    sentences: list[dict[str, Any]],
    keep_classes: set[str],
) -> str:
    """
    创建浓缩文本（只保留特定分类的句子）

    Args:
        sentences: 句子列表，每个包含 text, classification
        keep_classes: 要保留的分类

    Returns:
        浓缩后的文本
    """
    kept = [s["text"] for s in sentences if s.get("classification") in keep_classes]

    return "".join(kept)


def add_transitions(
    sentences: list[str],
    transition_words: list[str] | None = None,
) -> list[str]:
    """
    为浓缩文本添加过渡词以保持流畅

    Args:
        sentences: 句子列表
        transition_words: 过渡词列表

    Returns:
        添加过渡词后的句子列表
    """
    if transition_words is None:
        transition_words = ["此外", "另外", "同时", "再者"]

    # 简单实现：在句子间随机添加过渡词
    result = []
    for i, sentence in enumerate(sentences):
        result.append(sentence)
        # 在部分句子后添加过渡
        if i < len(sentences) - 1 and i % 3 == 0:
            result.append(transition_words[i % len(transition_words)])

    return result


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度（简单的词频余弦相似度）

    Args:
        text1: 文本1
        text2: 文本2

    Returns:
        相似度 (0-1)
    """
    if not text1 or not text2:
        return 0

    # 简单分词
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))

    if not words1 or not words2:
        return 0

    # 计算交集
    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0


def extract_formulas(text: str) -> list[str]:
    """
    从文本中提取公式（简单的模式匹配）

    Args:
        text: 文本

    Returns:
        公式列表
    """
    # 匹配常见的数学公式模式
    patterns = [
        r"[A-Z]\([s-zA-Z]\)\s*=\s*[^。！？.!?]+",  # G(s) = ...
        r"\([^)]+\)\s*=\s*[^。！？.!?]+",  # (x) = ...
        r"[a-zA-Z]+\s*=\s*\d+/\d+",  # x = 1/2
    ]

    formulas = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        formulas.extend(matches)

    return formulas


def extract_definitions(text: str) -> list[str]:
    """
    从文本中提取定义（"XXX是XXX"句式）

    Args:
        text: 文本

    Returns:
        定义列表
    """
    patterns = [
        r"([^，。]{2,10})是([^，。]{2,30})[，。]",
        r"([^，。]{2,10})定义为([^，。]{2,30})[，。]",
        r"([^，。]{2,10})是指([^，。]{2,30})[，。]",
    ]

    definitions = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for term, definition in matches:
            definitions.append(f"{term}是{definition}")

    return definitions


def truncate_for_tts(
    text: str,
    max_length: int = 300,
    split_at_sentence: bool = True,
) -> list[str]:
    """
    将文本截断为适合 TTS 的片段

    Args:
        text: 输入文本
        max_length: 单段最大长度
        split_at_sentence: 是否按句子分割

    Returns:
        文本片段列表
    """
    if len(text) <= max_length:
        return [text]

    if split_at_sentence:
        # 按句子分割
        sentences = split_by_punctuation(text)

        chunks = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) <= max_length:
                current += sentence
            else:
                if current:
                    chunks.append(current)
                # 如果单个句子过长，强制分割
                if len(sentence) > max_length:
                    for i in range(0, len(sentence), max_length):
                        chunks.append(sentence[i:i + max_length])
                    current = ""
                else:
                    current = sentence

        if current:
            chunks.append(current)

        return chunks
    else:
        # 强制按长度分割
        return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def normalize_punctuation(text: str) -> str:
    """
    标准化标点符号（全角转半角等）

    Args:
        text: 输入文本

    Returns:
        标准化后的文本
    """
    # 全角标点转半角
    punctuation_map = {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
    }

    for full, half in punctuation_map.items():
        text = text.replace(full, half)

    return text
