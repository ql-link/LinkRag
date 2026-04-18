# -*- coding: utf-8 -*-
"""Orchestration layer that connects markdown parsing and chunking."""

from src.core.markdown_parser import MarkdownParser, ParseResult

from .base import BaseChunker
from .models import Chunk


class ChunkingEngine:
    """
        编排 `MarkdownParser -> BaseChunker` 的完整流程，作为 splitter 模块的主入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        chunker: BaseChunker,
        parser: MarkdownParser | None = None,
    ):
        """
            初始化 chunking 引擎，并注入分片策略与可选的解析器实现。

        Args:
            chunker: 负责具体分片逻辑的 chunker 实例。
            parser: 可选的 Markdown 解析器；未传入时使用默认 `MarkdownParser`。

        Returns:
            None.
        """
        self._parser = parser or MarkdownParser()
        self._chunker = chunker

    @property
    def parser(self) -> MarkdownParser:
        """
            暴露当前引擎持有的 Markdown 解析器实例。

        Args:
            None.

        Returns:
            MarkdownParser: 当前使用的解析器对象。
        """
        return self._parser

    @property
    def chunker(self) -> BaseChunker:
        """
            暴露当前引擎持有的分片策略实例。

        Args:
            None.

        Returns:
            BaseChunker: 当前使用的 chunker 对象。
        """
        return self._chunker

    def process(
        self,
        text: str,
        source_file: str | None = None,
        **kwargs,
    ) -> list[Chunk]:
        """
            执行完整同步流程：原始 Markdown 文本先解析，再交给 chunker 产出最终分片。

        Args:
            text: 原始 Markdown 文本。
            source_file: 可选的来源文件名，会透传到分片元数据。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        parse_result = self._parser.parse(text, source_file=source_file)
        return self._chunker.chunk_from_parse_result(parse_result, **kwargs)

    async def aprocess(
        self,
        text: str,
        source_file: str | None = None,
        **kwargs,
    ) -> list[Chunk]:
        """
            执行完整异步流程：原始 Markdown 文本先解析，再交给异步 chunker 产出分片。

        Args:
            text: 原始 Markdown 文本。
            source_file: 可选的来源文件名，会透传到分片元数据。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        parse_result = self._parser.parse(text, source_file=source_file)
        return await self._chunker.achunk_from_parse_result(parse_result, **kwargs)

    def process_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
        **kwargs,
    ) -> list[Chunk]:
        """
            执行完整同步流程：从文件读取 Markdown，解析后产出最终分片。

        Args:
            filepath: Markdown 文件路径。
            encoding: 文件编码，默认使用 `utf-8`。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        parse_result = self._parser.parse_file(filepath, encoding=encoding)
        return self._chunker.chunk_from_parse_result(parse_result, **kwargs)

    def process_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
            直接消费上游已生成的 `ParseResult`，跳过解析阶段继续执行分片。

        Args:
            parse_result: 已完成 Markdown 解析的结构化结果。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        return self._chunker.chunk_from_parse_result(parse_result, **kwargs)

    async def aprocess_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
        **kwargs,
    ) -> list[Chunk]:
        """
            执行完整异步流程：从文件读取 Markdown，解析后产出最终分片。

        Args:
            filepath: Markdown 文件路径。
            encoding: 文件编码，默认使用 `utf-8`。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        parse_result = self._parser.parse_file(filepath, encoding=encoding)
        return await self._chunker.achunk_from_parse_result(parse_result, **kwargs)

    async def aprocess_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
            直接消费上游已生成的 `ParseResult`，以异步方式继续执行分片。

        Args:
            parse_result: 已完成 Markdown 解析的结构化结果。
            **kwargs: 透传给 chunker 的扩展配置。

        Returns:
            list[Chunk]: 最终分片结果列表。
        """
        return await self._chunker.achunk_from_parse_result(parse_result, **kwargs)

    def parse_only(
        self,
        text: str,
        source_file: str | None = None,
    ) -> ParseResult:
        """
            仅执行 Markdown 解析，不触发分片逻辑，便于调试和预览中间结果。

        Args:
            text: 原始 Markdown 文本。
            source_file: 可选的来源文件名。

        Returns:
            ParseResult: 结构化解析结果。
        """
        return self._parser.parse(text, source_file=source_file)
