# -*- coding: utf-8 -*-
"""noop 第二阶段算法。"""

from __future__ import annotations

from .stage_models import CoarseChunk, CoarseChunkSet, FinalChunk, FinalChunkSet, StageIdFactory


class NoopStageTwoAlgorithm:
    """
    不做实际细分的第二阶段算法。

    Args:
        None.

    Returns:
        None.
    """

    name = "noop"

    async def run(self, coarse_set: CoarseChunkSet) -> FinalChunkSet:
        """
        将 CoarseChunkSet 等价转换为 FinalChunkSet。

        Args:
            coarse_set: 第一阶段输出的粗分片集合。

        Returns:
            FinalChunkSet: 可导出的最终内部分片集合。
        """
        id_factory = StageIdFactory("final")
        return FinalChunkSet(
            chunks=[
                self._to_final_chunk(chunk=chunk, id_factory=id_factory, coarse_set=coarse_set)
                for chunk in coarse_set.chunks
            ],
            source_file=coarse_set.source_file,
            stage1_strategy=coarse_set.strategy,
            stage2_strategy=self.name,
            metadata=dict(coarse_set.metadata),
        )

    def _to_final_chunk(
        self,
        *,
        chunk: CoarseChunk,
        id_factory: StageIdFactory,
        coarse_set: CoarseChunkSet,
    ) -> FinalChunk:
        """
        将单个粗分片转换为最终内部分片。

        Args:
            chunk: 第一阶段粗分片。
            id_factory: final ID 生成器。
            coarse_set: 第一阶段输出集合。

        Returns:
            FinalChunk: 转换后的最终内部分片。
        """
        source_coarse_chunk_id = (
            chunk.source_coarse_chunk_id if chunk.role == "derived_element" else chunk.id
        )
        return FinalChunk(
            id=id_factory.next(),
            content=chunk.content,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            element_types=list(chunk.element_types),
            heading_trail=list(chunk.heading_trail),
            heading_trails=[list(trail) for trail in chunk.heading_trails],
            role=chunk.role,
            stage1_strategy=chunk.strategy or coarse_set.strategy,
            stage2_strategy=self.name,
            source_coarse_chunk_id=source_coarse_chunk_id,
            metadata=dict(chunk.metadata),
        )
