# -*- coding: utf-8 -*-
"""splitter 派生元素读结构化字段（R2）单元测试。

覆盖：图片/表格描述取自 metadata 字段、字段缺失走兜底、原始表格取自 content。
"""

from src.core.markdown_parser import ElementType, MarkdownElement
from src.core.markdown_parser.models import (
    META_TABLE_SUMMARY,
    META_VISUAL_DESCRIPTION,
)
from src.core.splitter.element_derived_chunker import DerivedElementChunkBuilder


def _element(element_type: ElementType, content: str, metadata: dict | None = None):
    return MarkdownElement(
        type=element_type,
        content=content,
        start_line=0,
        end_line=0,
        metadata=metadata or {},
    )


def test_image_description_reads_field():
    element = _element(
        ElementType.IMAGE,
        "![x](u.png)",
        {"url": "u.png", META_VISUAL_DESCRIPTION: "X 架构示意"},
    )
    assert DerivedElementChunkBuilder._extract_image_description(element) == "X 架构示意"


def test_image_description_falls_back_to_alt_when_field_missing():
    element = _element(ElementType.IMAGE, "![Hero](u.png)", {"url": "u.png", "alt": "Hero"})
    assert DerivedElementChunkBuilder._extract_image_description(element) == "Hero"


def test_image_description_falls_back_to_placeholder():
    element = _element(ElementType.IMAGE, "![](u.png)", {"url": "u.png"})
    assert DerivedElementChunkBuilder._extract_image_description(element) == "未提供图片说明。"


def test_table_summary_reads_field():
    element = _element(ElementType.TABLE, "| a | b |", {META_TABLE_SUMMARY: "该表展示召回率"})
    assert DerivedElementChunkBuilder._extract_table_summary(element) == "该表展示召回率"


def test_table_summary_falls_back_to_placeholder():
    element = _element(ElementType.TABLE, "| a | b |", {})
    assert DerivedElementChunkBuilder._extract_table_summary(element) == "未提供表格总结。"


def test_raw_table_is_content_itself():
    raw = "| M | V |\n| :- | -: |\n| Recall | 0.82 |"
    assert DerivedElementChunkBuilder._extract_raw_table(raw) == raw
