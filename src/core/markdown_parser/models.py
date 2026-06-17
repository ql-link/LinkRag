# -*- coding: utf-8 -*-
"""
Markdown 解析数据模型

定义元素类型枚举和元素数据结构。
设计思路来自 RAGFlow 的 MarkdownElementExtractor，
但使用更规范的数据模型替代原始 dict，增加了更多元素类型。
"""

import re
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
            - visual_description: str (仅 IMAGE 类型，解码归位的视觉描述)
            - table_summary: str (仅 TABLE 类型，解码归位的表格总结)
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
        return "\n\n".join(
            block for element in self.elements if (block := self._materialize_element(element))
        )

    @staticmethod
    def _materialize_element(element: "MarkdownElement") -> str:
        """把元素还原为 markdown 文本块，并把结构化描述字段重新编码为标记。

        这是 ``MarkdownParser.parse()`` 解码的对称逆操作：解码把标记从 content 抽进
        ``metadata`` 字段，本方法在序列化时把字段重新编码回标记，使
        ``parse() -> to_markdown()`` 形成无损往返（重新 parse 可再次解码出同样字段）。

        编码态结果（描述还在 content、字段未设置）经过本方法不会被重复编码——字段为空即不追加。
        """
        if not element.content:
            return ""
        parts = [element.content]

        visual_description = element.metadata.get(META_VISUAL_DESCRIPTION)
        url = element.metadata.get("url")
        if visual_description and url:
            parts.append(build_vision_marker(url, visual_description))

        table_summary = element.metadata.get(META_TABLE_SUMMARY)
        if table_summary:
            parts.append(build_table_marker(table_summary))

        return "\n\n".join(parts)


# ===== 增强描述编解码（markdown_parser 私有，对外不可见） =====
#
# 增强阶段把图片/表格描述「编码」为内联文本标记写入 element.content，使其能随
# markdown 一起持久化并扛过 to_markdown() -> 重新 parse() 的字符串往返；
# MarkdownParser.parse() 再把标记「解码」回结构化字段并从 content 剥离。
# 标记格式只在此处定义，编码（llm_integration）与解码（parser）共用，单一来源。

# metadata 字段键
META_VISUAL_DESCRIPTION = "visual_description"  # IMAGE 元素：视觉描述
META_TABLE_SUMMARY = "table_summary"  # TABLE 元素：表格总结

# 内联图描述改写后的可读段落前缀（内联图无独立元素、所在段落非 derived 锚点，
# 故其描述以干净正文段落形式留存，而非结构化字段）。
INLINE_IMAGE_DESCRIPTION_PREFIX = "图片说明："

# 标记前缀（视觉标记带 src=<url> 以便同段多图精确回绑；表格单元素无需 url）
_VISION_MARKER_OPEN = "[视觉描述|src="
_TABLE_MARKER_OPEN = "[表格总结:"


def build_vision_marker(url: str, desc: str) -> str:
    """构造视觉描述编码标记：``[视觉描述|src=<url>: <desc>]``。"""
    return f"{_VISION_MARKER_OPEN}{url}: {desc}]"


def build_table_marker(desc: str) -> str:
    """构造表格总结编码标记：``[表格总结: <desc>]``。"""
    return f"{_TABLE_MARKER_OPEN} {desc}]"


def vision_marker_prefix(url: str) -> str:
    """某 url 的视觉标记前缀，用于编码侧防重复 append。"""
    return f"{_VISION_MARKER_OPEN}{url}:"


# 解码正则：段落整段恰为一个标记块时匹配（先对 content.strip() 做 fullmatch 语义）。
# 视觉：url 用 \S+? 非贪婪，以「冒号+空白」为 url/desc 分隔；url 无空白，故 https:// 内
# 的冒号（后接 '/'）不会被误判为分隔符。desc 用 .* + DOTALL 贪婪吃到结尾最后一个 ']'。
VISION_MARKER_RE = re.compile(r"^\[视觉描述\|src=(?P<url>\S+?):\s(?P<desc>.*)\]$", re.DOTALL)
TABLE_MARKER_RE = re.compile(r"^\[表格总结:\s(?P<desc>.*)\]$", re.DOTALL)
