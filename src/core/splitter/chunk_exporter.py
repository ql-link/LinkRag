# -*- coding: utf-8 -*-
"""将最终内部分片导出为对外 Chunk。"""

from __future__ import annotations

from src.core.markdown_parser import ElementType

from .models import Chunk
from .stage_models import FinalChunk, FinalChunkSet
from .validators import SplitterOutputValidationError


class ChunkExporter:
    """
    FinalChunkSet 到 list[Chunk] 的统一导出器。

    Args:
        None.

    Returns:
        None.
    """

    PROTECTED_TYPE_VALUES = frozenset(
        [
            ElementType.CODE_BLOCK.value,
            ElementType.MATH_BLOCK.value,
            ElementType.TABLE.value,
            ElementType.IMAGE.value,
        ]
    )

    def export(self, final_set: FinalChunkSet) -> list[Chunk]:
        """
        导出最终 Chunk 列表。

        Args:
            final_set: 第二阶段输出的最终内部分片集合。

        Returns:
            list[Chunk]: 下游稳定消费的最终分片列表。

        Raises:
            SplitterOutputValidationError: derived chunk 无法映射 source chunk。
        """
        source_index_by_coarse_id: dict[str, int] = {}
        chunks: list[Chunk] = []

        for index, final_chunk in enumerate(final_set.chunks):
            if final_chunk.role != "derived_element" and final_chunk.source_coarse_chunk_id:
                source_index_by_coarse_id.setdefault(final_chunk.source_coarse_chunk_id, index)
            chunks.append(
                Chunk(
                    content=final_chunk.content,
                    start_line=final_chunk.start_line,
                    end_line=final_chunk.end_line,
                    metadata=self._base_metadata(final_chunk, final_set, index),
                )
            )

        for final_chunk, chunk in zip(final_set.chunks, chunks):
            if final_chunk.role != "derived_element":
                continue
            source_coarse_chunk_id = final_chunk.source_coarse_chunk_id
            source_index = source_index_by_coarse_id.get(str(source_coarse_chunk_id))
            if source_index is None:
                raise SplitterOutputValidationError(
                    "derived final chunk references missing source coarse chunk id: "
                    f"{source_coarse_chunk_id!r}."
                )
            chunk.metadata["source_chunk_index"] = source_index

        return chunks

    def _base_metadata(
        self,
        final_chunk: FinalChunk,
        final_set: FinalChunkSet,
        chunk_index: int,
    ) -> dict:
        """
        构造最终 Chunk metadata。

        Args:
            final_chunk: 待导出的最终内部分片。
            final_set: 第二阶段输出集合。
            chunk_index: 当前最终 Chunk 序号。

        Returns:
            dict: 最终 Chunk metadata。
        """
        stage1_strategy = final_chunk.stage1_strategy or final_set.stage1_strategy
        stage2_strategy = final_chunk.stage2_strategy or final_set.stage2_strategy
        metadata = dict(final_chunk.metadata)
        metadata.update(
            {
                "chunk_index": chunk_index,
                "element_types": list(final_chunk.element_types),
                "chunk_role": final_chunk.role,
                "heading_trail": list(final_chunk.heading_trail),
                "split_strategy": f"{stage1_strategy} + {stage2_strategy}",
            }
        )
        if final_chunk.heading_trails:
            metadata["heading_trails"] = [list(trail) for trail in final_chunk.heading_trails]
        if final_set.source_file:
            metadata["source_file"] = final_set.source_file
        protected_element_types = sorted(
            {value for value in final_chunk.element_types if value in self.PROTECTED_TYPE_VALUES}
        )
        if final_chunk.role != "derived_element" and protected_element_types:
            metadata["protected_element_types"] = protected_element_types
        return metadata
