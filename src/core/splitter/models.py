# -*- coding: utf-8 -*-
"""
Chunking 数据模型

定义分片产物的数据结构。Chunk 是 chunking 引擎的最小输出单元，
下游 Embedding / VectorStore 直接消费此对象。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """文本分片

    chunking 引擎的输出单元，每个 Chunk 代表一段可独立检索的文本。

    Attributes:
        content: 分片文本内容
        start_line: 在源文档中的起始行号 (0-based)
        end_line: 在源文档中的结束行号 (0-based, inclusive)
        metadata: 可扩展的元数据字段，如:
            - source_file: str (来源文件名)
            - heading_trail: list[str] (标题面包屑路径)
            - element_types: list[str] (包含的元素类型)
            - chunk_index: int (该分片在分片列表中的序号)
    """

    content: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """分片字符数"""
        return len(self.content)

    @property
    def line_count(self) -> int:
        """分片行数"""
        return self.end_line - self.start_line + 1

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        """从字典反序列化"""
        return cls(
            content=data["content"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        preview = preview.replace("\n", "\\n")
        return f"Chunk(L{self.start_line}-{self.end_line}, {self.char_count}ch, {preview!r})"
