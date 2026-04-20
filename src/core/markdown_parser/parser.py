# -*- coding: utf-8 -*-
"""
Markdown 解析器主入口

组合 MarkdownScanner、TableExtractor、ImageExtractor，
提供统一的解析 API。

设计对标 RAGFlow 的 rag/app/naive.py 中的 Markdown.__call__() 方法，
但不包含图片下载、Vision 增强、超链接提取等上层功能。
"""

from .models import ImageRef, MarkdownElement, ParseResult, ElementType, TableRef
from .scanner import MarkdownScanner
from .image_extractor import ImageExtractor


class MarkdownParser:
    """Markdown 解析器

    将 Markdown 文本解析为结构化的 ParseResult。

    对标 RAGFlow 的 Markdown 类（rag/app/naive.py L575-710），
    简化为仅关注解析，不涉及分片和图片加载。

    用法:
        parser = MarkdownParser()
        result = parser.parse("# Hello\\n\\nWorld\\n\\n| A | B |\\n|--|--|\\n| 1 | 2 |")
        print(result.elements)  # 扁平元素列表
        print(result.tables)    # 提取出的表格
        print(result.images)    # 图片引用
    """

    def __init__(self):
        self._scanner = MarkdownScanner()
        self._image_extractor = ImageExtractor()

    def parse(
        self,
        text: str,
        source_file: str | None = None,
    ) -> ParseResult:
        """完整解析 Markdown 文本

        执行流程对标 RAGFlow Markdown.__call__() L673-710:
        1. 图片 URL 提取
        2. 逐行扫描 → 元素列表 (原生拆出表格)

        与 RAGFlow 的关键差异:
        - RAGFlow 依赖于提前将内容切割/剪切。
        - 本架构采用了原生行扫描识别表格，保证元素的绝对物理位置和类型严谨性。

        Args:
            text: 原始 Markdown 文本
            source_file: 来源文件名（可选，记录到 ParseResult）

        Returns:
            ParseResult 包含 elements, tables, images, source_file
        """
        # ----- 步骤1: 图片 URL 提取 -----
        images = self._image_extractor.extract(text)

        # ----- 步骤2: 逐行扫描 -----
        elements = self._scanner.scan(text)
        
        # ----- 步骤3: 提取表格供外部 Pipeline 使用 -----
        tables = [
            TableRef(content=e.content, start_line=e.start_line, end_line=e.end_line)
            for e in elements
            if e.type == ElementType.TABLE
        ]

        return ParseResult(
            elements=elements,
            tables=tables,
            images=images,
            source_file=source_file,
            remainder=text,
        )

    def parse_flat(self, text: str) -> list[MarkdownElement]:
        """仅扫描: 文本 → 扁平元素列表 (不提取图片)

        轻量级接口，等价于直接调用 MarkdownScanner.scan()

        Args:
            text: 原始 Markdown 文本

        Returns:
            按文档顺序排列的 MarkdownElement 列表
        """
        return self._scanner.scan(text)

    def parse_images(self, text: str) -> list[ImageRef]:
        """仅提取图片引用

        Args:
            text: 原始 Markdown 文本

        Returns:
            图片引用列表
        """
        return self._image_extractor.extract(text)

    def parse_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
    ) -> ParseResult:
        """解析 Markdown 文件

        Args:
            filepath: 文件路径
            encoding: 文件编码，默认为 utf-8

        Returns:
            ParseResult
        """
        with open(filepath, "r", encoding=encoding, errors="ignore") as f:
            text = f.read()

        return self.parse(text, source_file=filepath)
