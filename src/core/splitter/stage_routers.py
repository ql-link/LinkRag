# -*- coding: utf-8 -*-
"""splitter 阶段算法路由。"""

from __future__ import annotations

from collections.abc import Iterable

from .stage_contracts import StageOneAlgorithm, StageTwoAlgorithm
from .stage_models import CoarseChunkSet, FinalChunkSet, SplitInput


class UnknownStageAlgorithmError(ValueError):
    """
    配置的阶段算法名不存在时抛出。

    Args:
        None.

    Returns:
        None.
    """


class StageOneRouter:
    """
    第一阶段算法路由器。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        algorithm_name: str,
        algorithms: Iterable[StageOneAlgorithm],
    ) -> None:
        """
        初始化第一阶段路由。

        Args:
            algorithm_name: 配置指定的第一阶段算法名。
            algorithms: 当前可用的第一阶段算法集合。

        Returns:
            None.

        Raises:
            UnknownStageAlgorithmError: 配置算法名不存在。
        """
        self.algorithm_name = algorithm_name
        self._algorithms = {algorithm.name: algorithm for algorithm in algorithms}
        if algorithm_name not in self._algorithms:
            raise UnknownStageAlgorithmError(f"Unknown stage one algorithm: {algorithm_name!r}.")

    def run(self, split_input: SplitInput) -> CoarseChunkSet:
        """
        执行配置选中的第一阶段算法。

        Args:
            split_input: splitter 内部输入。

        Returns:
            CoarseChunkSet: 第一阶段输出集合。
        """
        return self._algorithms[self.algorithm_name].run(split_input)

    @property
    def algorithm(self) -> StageOneAlgorithm:
        """
        返回当前配置选中的第一阶段算法实例。

        Args:
            None.

        Returns:
            StageOneAlgorithm: 当前第一阶段算法实例。
        """
        return self._algorithms[self.algorithm_name]


class StageTwoRouter:
    """
    第二阶段算法路由器。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        algorithm_name: str,
        algorithms: Iterable[StageTwoAlgorithm],
    ) -> None:
        """
        初始化第二阶段路由。

        Args:
            algorithm_name: 配置指定的第二阶段算法名。
            algorithms: 当前可用的第二阶段算法集合。

        Returns:
            None.

        Raises:
            UnknownStageAlgorithmError: 配置算法名不存在。
        """
        self.algorithm_name = algorithm_name
        self._algorithms = {algorithm.name: algorithm for algorithm in algorithms}
        if algorithm_name not in self._algorithms:
            raise UnknownStageAlgorithmError(f"Unknown stage two algorithm: {algorithm_name!r}.")

    async def run(self, coarse_set: CoarseChunkSet) -> FinalChunkSet:
        """
        执行配置选中的第二阶段算法。

        Args:
            coarse_set: 第一阶段输出集合。

        Returns:
            FinalChunkSet: 第二阶段输出集合。
        """
        return await self._algorithms[self.algorithm_name].run(coarse_set)

    @property
    def algorithm(self) -> StageTwoAlgorithm:
        """
        返回当前配置选中的第二阶段算法实例。

        Args:
            None.

        Returns:
            StageTwoAlgorithm: 当前第二阶段算法实例。
        """
        return self._algorithms[self.algorithm_name]
