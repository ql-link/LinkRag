# -*- coding: utf-8 -*-
"""
Markdown 解析数据模型

定义元素类型枚举和元素数据结构。
设计思路来自 RAGFlow 的 MarkdownElementExtractor，
但使用更规范的数据模型替代原始 dict，增加了更多元素类型。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ElementType(str, Enum):
    """Markdown 元素类型枚举

    继承 str 使枚举值可直接用于字符串比较和序列化。
    RAGFlow 原始实现使用硬编码字符串 ("header", "code_block" 等)，
    这里改为枚举以获得类型安全性。
    """

    HEADING = "heading"
    """标题 (# ~ ######)"""

    PARAGRAPH = "paragraph"
    """普通段落（连续的非空行文本）"""

    CODE_BLOCK = "code_block"
    """围栏代码块 (``` ... ```)"""

    LIST = "list"
    """列表块（无序 -/*/ + 或有序 1./2. ）"""

    BLOCKQUOTE = "blockquote"
    """引用块 (> ...)"""

    TABLE = "table"
    """表格（Markdown 或 HTML 格式）"""

    IMAGE = "image"
    """图片引用 (![alt](url) 或 <img>)"""

    HORIZONTAL_RULE = "hr"
    """水平线 (--- / *** / ___)"""

    FRONT_MATTER = "front_matter"
    """YAML front matter (--- ... ---)"""

    MATH_BLOCK = "math_block"
    """公式块 ($$ ... $$ 或 \\[ ... \\])"""


@dataclass
class MarkdownElement:
    """扁平 Markdown 元素

    逐行扫描器的输出单元。每个元素代表 Markdown 文档中一个独立的块级结构。
    RAGFlow 原始实现使用 dict: {"type", "content", "start_line", "end_line"}，
    这里用 dataclass 替代，增加了 metadata 扩展能力。

    Attributes:
        type: 元素类型
        content: 元素的原始文本内容
        start_line: 在源文档中的起始行号 (0-based)
        end_line: 在源文档中的结束行号 (0-based, inclusive)
        metadata: 可扩展的元数据字段，如:
            - heading_level: int (1-6, 仅 HEADING 类型)
            - language: str (仅 CODE_BLOCK 类型)
            - url: str (仅 IMAGE 类型)
            - alt: str (仅 IMAGE 类型)
    """

    type: ElementType
    content: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典，方便持久化和传输"""
        return {
            "type": self.type.value,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MarkdownElement":
        """从字典反序列化"""
        return cls(
            type=ElementType(data["type"]),
            content=data["content"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        content_preview = content_preview.replace("\n", "\\n")
        return f"MarkdownElement({self.type.value}, L{self.start_line}-{self.end_line}, {content_preview!r})"


@dataclass
class ImageRef:
    """图片引用信息

    对应 RAGFlow 中 Markdown.extract_image_urls_with_lines() 返回的
    {"url": str, "line": int}，增加了 alt 文本。

    Attributes:
        url: 图片 URL（可以是 HTTP 链接或本地路径）
        line: 图片引用所在行号 (0-based)
        alt: 图片的 alt 文本（可选）
    """

    url: str
    line: int
    alt: str = ""

    def to_dict(self) -> dict:
        return {"url": self.url, "line": self.line, "alt": self.alt}


@dataclass
class TableRef:
    """表格引用信息

    记录了独立表格文本在原文中的绝对物理位置（行号段），便于大模型后期回填。

    Attributes:
        content: 表格原始 Markdown 文本
        start_line: 所在首行号 (0-based)
        end_line: 所在尾行号 (0-based)
    """
    content: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict:
        return {"content": self.content, "start_line": self.start_line, "end_line": self.end_line}


@dataclass
class ParseResult:
    """解析结果

    主入口 MarkdownParser.parse() 的返回值，汇总所有解析产物。

    Attributes:
        elements: 扁平元素列表（按文档顺序）
        tables: 提取出的表格列表（原始 Markdown 文本）
        images: 提取出的图片引用列表
        source_file: 来源文件名（可选）
        remainder: 移除表格后的剩余文本
    """

    elements: list[MarkdownElement]
    tables: list[TableRef]
    images: list[ImageRef]
    source_file: str | None = None
    remainder: str = ""

    def to_dict(self) -> dict:
        return {
            "elements": [e.to_dict() for e in self.elements],
            "tables": [t.to_dict() for t in self.tables],
            "images": [img.to_dict() for img in self.images],
            "source_file": self.source_file,
        }

    def to_markdown(self) -> str:
        if not self.elements:
            return self.remainder
        return "\n\n".join(element.content for element in self.elements if element.content)
