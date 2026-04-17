# -*- coding: utf-8 -*-
"""
Chunking 引擎

编排 markdown_parser → chunker 的完整管线。
ChunkingEngine 是 splitter 模块的主入口，负责衔接上游解析和下游分片策略。
"""

from src.core.markdown_parser import MarkdownParser, ParseResult
from .base import BaseChunker
from .models import Chunk


class ChunkingEngine:
    """Chunking 引擎

    编排 MarkdownParser → BaseChunker 的完整管线。

    用法:
        from src.core.splitter import ChunkingEngine
        from my_chunkers import MyChunker

        engine = ChunkingEngine(chunker=MyChunker())
        chunks = engine.process("# Hello\\n\\nWorld")
        chunks = engine.process_file("docs/example.md")

    设计原则:
        - 组合而非继承: 通过构造函数注入 parser 和 chunker
        - 单一职责: 仅负责编排，不包含分片逻辑
        - 可替换: parser 和 chunker 均可由外部注入
    """

    def __init__(
        self,
        chunker: BaseChunker,
        parser: MarkdownParser | None = None,
    ):
        """初始化 ChunkingEngine

        Args:
            chunker: 分片策略实例（用户自定义）
            parser: Markdown 解析器实例（可选，默认创建标准 MarkdownParser）
        """
        self._parser = parser or MarkdownParser()
        self._chunker = chunker

    @property
    def parser(self) -> MarkdownParser:
        """获取当前解析器实例"""
        return self._parser

    @property
    def chunker(self) -> BaseChunker:
        """获取当前分片策略实例"""
        return self._chunker

    def process(
        self,
        text: str,
        source_file: str | None = None,
        **kwargs,
    ) -> list[Chunk]:
        """完整管线: 原始文本 → 解析 → 分片

        Args:
            text: 原始 Markdown 文本
            source_file: 来源文件名（可选）
            **kwargs: 透传给 chunker.chunk()

        Returns:
            Chunk 列表
        """
        parse_result = self._parser.parse(text, source_file=source_file)
        return self._chunker.chunk_from_parse_result(parse_result, **kwargs)

    def process_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
        **kwargs,
    ) -> list[Chunk]:
        """完整管线: 文件路径 → 解析 → 分片

        Args:
            filepath: Markdown 文件路径
            encoding: 文件编码，默认 utf-8
            **kwargs: 透传给 chunker.chunk()

        Returns:
            Chunk 列表
        """
        parse_result = self._parser.parse_file(filepath, encoding=encoding)
        return self._chunker.chunk_from_parse_result(parse_result, **kwargs)

    def parse_only(
        self,
        text: str,
        source_file: str | None = None,
    ) -> ParseResult:
        """仅解析，不分片（调试/预览用）

        Args:
            text: 原始 Markdown 文本
            source_file: 来源文件名（可选）

        Returns:
            ParseResult
        """
        return self._parser.parse(text, source_file=source_file)
