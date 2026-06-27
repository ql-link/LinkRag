"""会话标题 prompt 工具单测：清洗与首问截断兜底（LINK-209）。"""

from __future__ import annotations

import pytest

from src.core.prompts.conversation_title import (
    TITLE_MAX_CHARS,
    build_title_user_prompt,
    clean_title,
    fallback_title_from_query,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"RAG 入门"', "RAG 入门"),  # 剥英文双引号
        ("「如何配置向量库」", "如何配置向量库"),  # 剥中文直角引号
        ("《深度学习》", "深度学习"),  # 剥书名号
        ('"「嵌套引号」"', "嵌套引号"),  # 反复剥多层包裹
        ("多行\n标题", "多行 标题"),  # 换行压平为空格
        ("  含首尾空白  ", "含首尾空白"),
        ("结尾标点。", "结尾标点"),  # 去结尾标点
        ("", None),
        (None, None),
        ("。。。", None),  # 仅标点清洗后为空
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_truncates_to_max():
    long = "标" * (TITLE_MAX_CHARS + 20)
    cleaned = clean_title(long)
    assert cleaned is not None and len(cleaned) == TITLE_MAX_CHARS


def test_fallback_always_non_empty():
    assert fallback_title_from_query("你好") == "你好"
    # 超长 query 截断到上限
    long_q = "如何在生产环境部署 RAG 系统" * 10
    fb = fallback_title_from_query(long_q)
    assert 0 < len(fb) <= TITLE_MAX_CHARS
    # 极端：纯标点也兜底为「新对话」，绝不返回空串
    assert fallback_title_from_query("？？？") == "新对话"


def test_build_title_user_prompt_embeds_truncated_query():
    prompt = build_title_user_prompt("  什么是 RAG  ")
    assert "什么是 RAG" in prompt
