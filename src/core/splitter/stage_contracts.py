# -*- coding: utf-8 -*-
"""splitter 阶段算法协议。"""

from __future__ import annotations

from typing import Protocol

from .stage_models import CoarseChunkSet, FinalChunkSet, SplitInput


class StageOneAlgorithm(Protocol):
    """
    第一阶段算法协议。

    Args:
        None.

    Returns:
        None.
    """

    name: str

    def run(self, split_input: SplitInput) -> CoarseChunkSet:
        """
        执行第一阶段分片。

        Args:
            split_input: splitter 内部输入模型。

        Returns:
            CoarseChunkSet: 第一阶段粗分片集合。
        """
        ...


class StageTwoAlgorithm(Protocol):
    """
    第二阶段算法协议。

    Args:
        None.

    Returns:
        None.
    """

    name: str

    async def run(self, coarse_set: CoarseChunkSet) -> FinalChunkSet:
        """
        执行第二阶段处理。

        Args:
            coarse_set: 第一阶段输出的粗分片集合。

        Returns:
            FinalChunkSet: 可导出的最终内部分片集合。
        """
        ...
