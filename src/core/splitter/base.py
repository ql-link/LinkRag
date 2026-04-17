# -*- coding: utf-8 -*-
"""
Chunker 抽象基类

定义分片策略的接口契约。所有具体的 chunking 实现必须继承此基类。
用户通过实现 chunk() 方法注入自己的分片逻辑。
"""

from abc import ABC, abstractmethod

from src.core.markdown_parser.models import MarkdownElement, ParseResult
from .models import Chunk


class BaseChunker(ABC):
    """分片策略抽象基类

    定义 chunking 阶段的接口契约。

    典型的继承实现:
        class MyChunker(BaseChunker):
            def chunk(self, elements, **kwargs):
                # 自定义分片逻辑
                ...

    设计原则:
        - 输入: MarkdownElement 列表 (由 markdown_parser 产出)
        - 输出: Chunk 列表 (供下游 Embedding 消费)
        - 不修改输入数据，保持无副作用
    """

    @abstractmethod
    def chunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """将元素列表分片

        Args:
            elements: markdown_parser 产出的扁平元素列表（按文档顺序）
            **kwargs: 预留扩展参数，如 max_chunk_size, overlap 等

        Returns:
            按文档顺序排列的 Chunk 列表
        """
        ...

    def chunk_from_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """便捷方法: 直接从 ParseResult 分片

        从 MarkdownParser.parse() 的输出直接进入分片流程，
        自动将 source_file 注入到每个 Chunk 的 metadata 中。

        Args:
            parse_result: MarkdownParser.parse() 的返回值
            **kwargs: 透传给 chunk()

        Returns:
            Chunk 列表
        """
        chunks = self.chunk(parse_result.elements, **kwargs)

        # 自动注入 source_file
        if parse_result.source_file:
            for c in chunks:
                c.metadata.setdefault("source_file", parse_result.source_file)

        return chunks
