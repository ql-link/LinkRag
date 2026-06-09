# -*- coding: utf-8 -*-
"""splitter 内部阶段契约模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.markdown_parser import MarkdownElement


@dataclass(slots=True)
class SplitInput:
    """
    splitter 内部输入模型。

    Args:
        None.

    Returns:
        None.
    """

    elements: list[MarkdownElement]
    source_file: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProtectedRange:
    """
    记录 mixed chunk 内第二阶段默认不得盲切的结构化元素范围。

    Args:
        None.

    Returns:
        None.
    """

    kind: str
    start_line: int
    end_line: int
    element_index: int
    reason: str = "protected_element"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoarseChunk:
    """
    第一阶段算法输出的单个粗分片。

    Args:
        None.

    Returns:
        None.
    """

    id: str
    content: str
    start_line: int
    end_line: int
    token_count: int
    source_element_indexes: list[int]
    element_types: list[str]
    protected_ranges: list[ProtectedRange]
    heading_trail: list[str]
    heading_trails: list[list[str]]
    role: str
    strategy: str
    source_coarse_chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoarseChunkSet:
    """
    第一阶段算法输出集合，仅供第二阶段消费。

    Args:
        None.

    Returns:
        None.
    """

    chunks: list[CoarseChunk]
    source_file: str | None = None
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FinalChunk:
    """
    第二阶段输出的最终内部分片。

    Args:
        None.

    Returns:
        None.
    """

    id: str
    content: str
    start_line: int
    end_line: int
    element_types: list[str]
    heading_trail: list[str]
    heading_trails: list[list[str]]
    role: str
    stage1_strategy: str
    stage2_strategy: str
    source_coarse_chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FinalChunkSet:
    """
    第二阶段输出集合，可由 exporter 导出为最终 Chunk。

    Args:
        None.

    Returns:
        None.
    """

    chunks: list[FinalChunk]
    source_file: str | None = None
    stage1_strategy: str = ""
    stage2_strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class StageIdFactory:
    """
    生成运行内唯一、顺序确定的阶段内部 ID。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(self, prefix: str) -> None:
        """
        初始化 ID 生成器。

        Args:
            prefix: ID 前缀，例如 ``coarse`` 或 ``final``。

        Returns:
            None.
        """
        self.prefix = prefix
        self._counter = 0

    def next(self) -> str:
        """
        返回下一个顺序 ID。

        Args:
            None.

        Returns:
            str: 形如 ``coarse_000001`` 的运行内稳定 ID。
        """
        self._counter += 1
        return f"{self.prefix}_{self._counter:06d}"
