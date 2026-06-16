# -*- coding: utf-8 -*-
"""输入适配层，将解析产物归一为 SplitInput。"""

from __future__ import annotations

from src.core.markdown_parser import MarkdownElement, ParseResult

from .stage_models import SplitInput


class InputAdapter:
    """
    splitter 输入适配器。

    Args:
        None.

    Returns:
        None.
    """

    @staticmethod
    def from_elements(
        elements: list[MarkdownElement],
        *,
        source_file: str | None = None,
        metadata: dict | None = None,
    ) -> SplitInput:
        """
        从 MarkdownElement 列表构造 SplitInput。

        Args:
            elements: parser 已生成的结构化 Markdown 元素。
            source_file: 可选来源文件名。
            metadata: 可选文档级扩展信息。

        Returns:
            SplitInput: splitter 内部输入模型。
        """
        return SplitInput(
            elements=list(elements),
            source_file=source_file,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def from_parse_result(parse_result: ParseResult) -> SplitInput:
        """
        从 ParseResult 构造 SplitInput。

        Args:
            parse_result: parser 产出的结构化解析结果。

        Returns:
            SplitInput: splitter 内部输入模型。
        """
        return SplitInput(
            elements=list(parse_result.elements),
            source_file=parse_result.source_file,
            metadata={},
        )
