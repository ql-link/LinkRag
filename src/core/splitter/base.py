# -*- coding: utf-8 -*-
"""Base interfaces for splitter implementations."""

from abc import ABC, abstractmethod

from src.core.markdown_parser import MarkdownElement, ParseResult

from .models import Chunk


class BaseChunker(ABC):
    """
        定义 splitter 阶段的统一抽象接口，约束所有分片策略的输入输出形式。

    Args:
        None.

    Returns:
        None.
    """

    @abstractmethod
    def chunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
            将解析后的 Markdown 元素序列切分为按文档顺序排列的 Chunk 列表。

        Args:
            elements: `markdown_parser` 输出的扁平元素列表。
            **kwargs: 透传给具体 chunker 的扩展配置，例如长度约束或 overlap 参数。

        Returns:
            list[Chunk]: 分片后的结果列表。
        """
        ...

    def chunk_from_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
            直接消费 `ParseResult` 执行分片，并自动把 `source_file` 注入每个 Chunk 的元数据。

        Args:
            parse_result: 解析器产出的结构化结果对象。
            **kwargs: 透传给 `chunk()` 的扩展配置。

        Returns:
            list[Chunk]: 已补齐来源文件信息的分片结果。
        """
        chunks = self.chunk(parse_result.elements, **kwargs)

        if parse_result.source_file:
            for chunk in chunks:
                chunk.metadata.setdefault("source_file", parse_result.source_file)

        return chunks

    async def achunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
            提供异步分片入口，默认回退到同步 `chunk()` 实现。

        Args:
            elements: `markdown_parser` 输出的扁平元素列表。
            **kwargs: 透传给 `chunk()` 的扩展配置。

        Returns:
            list[Chunk]: 分片结果列表。
        """
        return self.chunk(elements, **kwargs)

    async def achunk_from_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
            提供异步版 `ParseResult` 入口，并在返回前补齐 `source_file` 元数据。

        Args:
            parse_result: 解析器产出的结构化结果对象。
            **kwargs: 透传给 `achunk()` 的扩展配置。

        Returns:
            list[Chunk]: 异步分片后的结果列表。
        """
        chunks = await self.achunk(parse_result.elements, **kwargs)

        if parse_result.source_file:
            for chunk in chunks:
                chunk.metadata.setdefault("source_file", parse_result.source_file)

        return chunks
