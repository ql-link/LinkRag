# -*- coding: utf-8 -*-
"""Data models used by the splitter and embedding pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """
        表示 splitter 阶段输出的基础分片对象，是下游 embedding 和入库的直接输入。

    Args:
        None.

    Returns:
        None.
    """

    content: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """
            返回当前 Chunk 文本内容的字符数，便于调试和可视化展示。

        Args:
            None.

        Returns:
            int: 当前 Chunk 的字符数量。
        """
        return len(self.content)

    @property
    def line_count(self) -> int:
        """
            返回当前 Chunk 覆盖的源文档行数。

        Args:
            None.

        Returns:
            int: 当前 Chunk 覆盖的行数。
        """
        return self.end_line - self.start_line + 1

    def to_dict(self) -> dict:
        """
            将 Chunk 序列化为普通字典，便于日志记录、持久化或接口传输。

        Args:
            None.

        Returns:
            dict: 序列化后的 Chunk 数据。
        """
        return {
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        """
            从字典恢复 Chunk 实例，便于从缓存或存储结果回构对象。

        Args:
            data: 由 `to_dict()` 生成或兼容的字典数据。

        Returns:
            Chunk: 反序列化得到的 Chunk 对象。
        """
        return cls(
            content=data["content"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        """
            生成适合调试输出的 Chunk 简短预览字符串。

        Args:
            None.

        Returns:
            str: 包含行号、字符数与文本预览的调试字符串。
        """
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        preview = preview.replace("\n", "\\n")
        return f"Chunk(L{self.start_line}-{self.end_line}, {self.char_count}ch, {preview!r})"


@dataclass
class EmbeddedChunk:
    """
        表示已经完成最终向量化的分片对象，用于检索索引或下游存储。

    Args:
        None.

    Returns:
        None.
    """

    chunk: Chunk
    embedding: list[float]
    embedding_model: str | None = None
    cached: bool = False

    @property
    def content(self) -> str:
        """
            透传底层 Chunk 的文本内容，便于调用方直接访问。

        Args:
            None.

        Returns:
            str: 分片文本内容。
        """
        return self.chunk.content

    @property
    def metadata(self) -> dict[str, Any]:
        """
            透传底层 Chunk 的元数据，便于调用方直接访问。

        Args:
            None.

        Returns:
            dict[str, Any]: 分片元数据字典。
        """
        return self.chunk.metadata

    def to_dict(self) -> dict[str, Any]:
        """
            将 `EmbeddedChunk` 序列化为字典，便于持久化或接口传输。

        Args:
            None.

        Returns:
            dict[str, Any]: 序列化后的嵌套字典结果。
        """
        return {
            "chunk": self.chunk.to_dict(),
            "embedding": self.embedding,
            "embedding_model": self.embedding_model,
            "cached": self.cached,
        }


@dataclass(slots=True)
class EmbeddingPipelineStats:
    """
        记录最终 Chunk 向量化阶段的关键统计信息，便于观测缓存与批处理效果。

    Args:
        None.

    Returns:
        None.
    """

    total_chunks: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    batch_count: int = 0
    embedding_model: str | None = None
